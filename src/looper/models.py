"""Data models for looper."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Loop:
    """A loop definition parsed from loops.md."""

    name: str
    interval: str  # 5-field cron or shorthand (10m, 1h, 30m, 1d)
    prompt: str
    active: bool = True
    created_at: Optional[str] = None  # ISO 8601
    paused_at: Optional[str] = None  # ISO 8601

    def to_markdown(self) -> str:
        lines = [f"## {self.name}"]
        lines.append(f"interval: {self.interval}")
        lines.append(f"active: {str(self.active).lower()}")
        if self.created_at:
            lines.append(f"created_at: {self.created_at}")
        if self.paused_at:
            lines.append(f"paused_at: {self.paused_at}")
        lines.append("")
        lines.append(self.prompt.strip())
        lines.append("")
        return "\n".join(lines)


@dataclass
class Job:
    """A live cron job from scheduled_tasks.json."""

    id: str
    name: str  # the marker/label used for dedup
    interval: str
    prompt: str
    created_at: str  # ISO 8601


@dataclass
class LoopStatus:
    """Status of a loop after diffing against live jobs."""

    loop: Loop
    job: Optional[Job] = None
    state: str = "unknown"  # active, missing, orphan, expiring, paused
    days_until_expiry: Optional[float] = None

    @property
    def icon(self) -> str:
        return {
            "active": "[green]●[/]",
            "missing": "[red]○[/]",
            "expiring": "[yellow]◐[/]",
            "paused": "[dim]◌[/]",
            "orphan": "[red]?[/]",
        }.get(self.state, "?")


@dataclass
class CheckResult:
    """Output of a full check/reconcile."""

    statuses: list[LoopStatus] = field(default_factory=list)
    orphan_jobs: list[Job] = field(default_factory=list)
    needs_sync: bool = False
    message: str = ""

    @property
    def active_count(self) -> int:
        return sum(1 for s in self.statuses if s.state == "active")

    @property
    def missing_count(self) -> int:
        return sum(1 for s in self.statuses if s.state == "missing")

    @property
    def expiring_count(self) -> int:
        return sum(1 for s in self.statuses if s.state == "expiring")
