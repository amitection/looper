"""Data models for looper."""

from __future__ import annotations

from dataclasses import dataclass
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
class LoopStatus:
    """A loop plus its display status (running / idle / paused)."""

    loop: Loop
    state: str = "idle"  # running, idle, paused

    @property
    def icon(self) -> str:
        return {
            "running": "[green]●[/]",
            "idle": "[yellow]○[/]",
            "paused": "[dim]◌[/]",
        }.get(self.state, "?")
