"""Tests for looper.harvest — capturing live Claude crons into loops.md."""

from __future__ import annotations

from pathlib import Path

import pytest

from looper.harvest import _slug, _unique_name, reconcile
from looper.models import Loop

NOW = 1_000_000.0


def cron(cid: str, schedule: str, prompt: str) -> dict:
    return {"id": cid, "schedule": schedule, "recurring": True, "prompt": prompt}


# -- slug / unique name ----------------------------------------------------


def test_slug_basic() -> None:
    assert _slug("print hello world") == "print-hello-world"


def test_slug_truncates_to_five_words() -> None:
    assert _slug("one two three four five six seven") == "one-two-three-four-five"


def test_slug_empty_fallback() -> None:
    assert _slug("!!!") == "loop"


def test_unique_name() -> None:
    assert _unique_name("hello", set()) == "hello"
    assert _unique_name("hello", {"hello"}) == "hello-2"
    assert _unique_name("hello", {"hello", "hello-2"}) == "hello-3"


# -- reconcile: create -----------------------------------------------------


def test_create_new_loop_from_cron() -> None:
    crons = [cron("abc", "* * * * *", "print hello world")]
    upserts, removes, new_map = reconcile(crons, {}, [], NOW)

    assert len(upserts) == 1
    assert upserts[0].name == "print-hello-world"
    assert upserts[0].interval == "* * * * *"
    assert upserts[0].prompt == "print hello world"
    assert removes == []
    assert new_map == {"abc": "print-hello-world"}


def test_create_skips_entries_without_id() -> None:
    crons = [{"schedule": "* * * * *", "prompt": "no id"}]
    upserts, removes, new_map = reconcile(crons, {}, [], NOW)
    assert upserts == []
    assert new_map == {}


def test_slash_command_prompts_are_skipped() -> None:
    """A cron whose prompt is itself a slash command (e.g. /loop) is not captured."""
    crons = [
        cron("x", "* * * * *", "/loop print PING"),
        cron("y", "* * * * *", "check the deploys"),
    ]
    upserts, removes, new_map = reconcile(crons, {}, [], NOW)
    names = [lp.name for lp in upserts]
    assert "check-the-deploys" in names
    assert all(not lp.prompt.startswith("/") for lp in upserts)
    assert "x" not in new_map  # the slash cron was ignored entirely


def test_two_distinct_prompts_get_unique_names() -> None:
    crons = [cron("a", "* * * * *", "do alpha"), cron("b", "0 9 * * *", "do beta")]
    upserts, _, new_map = reconcile(crons, {}, [], NOW)
    names = {lp.name for lp in upserts}
    assert names == {"do-alpha", "do-beta"}


# -- reconcile: re-inject bridge (no duplicates) ---------------------------


def test_reinjected_loop_matched_by_content_not_duplicated() -> None:
    """A loop already in loops.md, re-registered with a new id, is not re-added."""
    existing = [Loop(name="print-hello-world", interval="* * * * *", prompt="print hello world")]
    # New session re-injected it; Claude assigned a fresh id.
    crons = [cron("new-id-xyz", "* * * * *", "print hello world")]
    upserts, removes, new_map = reconcile(crons, {}, existing, NOW)

    assert upserts == []  # no duplicate created
    assert removes == []
    assert new_map == {"new-id-xyz": "print-hello-world"}  # id bound to existing loop


# -- reconcile: known id unchanged -----------------------------------------


def test_known_id_is_noop() -> None:
    existing = [Loop(name="hello", interval="* * * * *", prompt="print hello")]
    crons = [cron("abc", "* * * * *", "print hello")]
    prev = {"abc": "hello"}
    upserts, removes, new_map = reconcile(crons, prev, existing, NOW)
    assert upserts == []
    assert removes == []
    assert new_map == {"abc": "hello"}


# -- reconcile: delete -----------------------------------------------------


def test_vanished_cron_is_kept_not_deleted() -> None:
    """Additive: a cron gone from session_crons (expired/deleted) is KEPT.

    We can't tell expiry from a real delete, and dropping an expired loop would
    lose it — so harvest never removes. Removal is explicit (looper delete).
    """
    existing = [Loop(name="hello", interval="* * * * *", prompt="print hello")]
    prev = {"abc": "hello"}
    crons: list[dict] = []  # cron vanished (expired, say)
    upserts, removes, new_map = reconcile(crons, prev, existing, NOW)
    assert upserts == []      # nothing added
    assert removes == []      # nothing removed — loop stays in loops.md
    assert new_map == {}      # the dead id is no longer tracked as live


def test_expired_loop_can_be_rearmed() -> None:
    """After a loop vanishes, /start-loops re-binds it from loops.md (new id)."""
    existing = [Loop(name="hello", interval="* * * * *", prompt="print hello")]
    # Re-armed in a fresh session: a new cron id with the same content.
    crons = [cron("new-id", "* * * * *", "print hello")]
    upserts, removes, new_map = reconcile(crons, {}, existing, NOW)
    assert upserts == []                  # already in loops.md, not duplicated
    assert removes == []
    assert new_map == {"new-id": "hello"} # bound to the existing loop


# -- reconcile: in-session edit (additive — leaves the old entry) -----------


def test_in_session_edit_adds_new_keeps_old() -> None:
    """Native 'edit' = delete old + create new. Additive harvest keeps both;
    the stale old entry is cleaned up explicitly (the documented delete gap)."""
    existing = [Loop(name="print-hello", interval="* * * * *", prompt="print hello")]
    prev = {"old": "print-hello"}
    crons = [cron("new", "* * * * *", "print goodbye")]
    upserts, removes, new_map = reconcile(crons, prev, existing, NOW)

    assert [lp.name for lp in upserts] == ["print-goodbye"]  # new one captured
    assert removes == []                                     # old NOT auto-removed
    assert new_map == {"new": "print-goodbye"}


# -- reconcile: stable across repeated harvests ----------------------------


def test_repeated_harvest_is_idempotent() -> None:
    existing = [Loop(name="hello", interval="* * * * *", prompt="print hello")]
    crons = [cron("abc", "* * * * *", "print hello")]
    # First harvest binds the id
    _, _, map1 = reconcile(crons, {}, existing, NOW)
    # Second harvest with the same state changes nothing
    upserts, removes, map2 = reconcile(crons, map1, existing, NOW)
    assert upserts == []
    assert removes == []
    assert map2 == map1
