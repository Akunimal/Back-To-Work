"""Claude Code provider — zero-cost, local-only, EXACT limit detection.

It NEVER calls the Anthropic API (that would burn usage). Instead it reads Claude
Code's own session transcripts on disk and looks for the explicit usage-limit
marker the CLI writes when it actually gets rate-limited.

How it works:
  - Claude Code writes one JSONL transcript per session under
    ~/.claude/projects/**/*.jsonl.
  - When (and only when) you hit the rolling usage limit, Claude Code records a
    message whose text is:  `Claude Code usage limit reached|<unix_epoch>`
    where <unix_epoch> is the exact reset time in seconds.
  - We scan recent transcripts for that marker and report the most recent one.
    If its reset time is still in the future -> EXHAUSTED with the exact reset.
    Otherwise (no marker, or it already elapsed) -> AVAILABLE.

This is EXACT (not a 5-hour estimate): the reset time comes straight from the
marker Claude Code itself wrote. No API call, no guessing from activity.

Key fix vs. older versions: having recent activity does NOT mean you're out of
credit. Only the explicit limit marker means exhausted.

Options (all optional):
    lookback_hours = 6     # only scan transcripts touched within this window
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path

from ..models import QuotaState, Status
from .base import Provider, register

# The marker Claude Code writes on a real rate-limit, e.g.
#   Claude Code usage limit reached|1748736000
# Be liberal: match the phrase followed by a pipe and a 10–13 digit epoch.
_MARKER = re.compile(r"usage limit reached\|(\d{10,13})", re.IGNORECASE)


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


def _epoch_to_dt(raw: str) -> datetime:
    val = int(raw)
    if val > 1_000_000_000_000:  # milliseconds
        val //= 1000
    return datetime.fromtimestamp(val, tz=timezone.utc)


def _latest_marker(projects: Path, lookback_secs: float, now: datetime) -> datetime | None:
    """Return the reset time from the most recently written usage-limit marker
    across recent transcripts, or None if none found."""
    cutoff = now.timestamp() - lookback_secs
    best_mtime = -1.0
    best_reset: datetime | None = None

    for jsonl in projects.rglob("*.jsonl"):
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        try:
            text = jsonl.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        matches = _MARKER.findall(text)
        if not matches:
            continue
        # Within a file the relevant marker is the last one; across files prefer
        # the most recently modified transcript.
        if mtime > best_mtime:
            try:
                best_reset = _epoch_to_dt(matches[-1])
                best_mtime = mtime
            except (ValueError, OverflowError, OSError):
                continue

    return best_reset


@register("claude_code")
class ClaudeCodeProvider(Provider):
    def read_state(self) -> QuotaState:
        home = _claude_home()
        projects = home / "projects"
        if not projects.exists():
            return QuotaState(
                Status.UNKNOWN,
                detail=f"{projects} not found; is Claude Code installed here?",
            )

        lookback = float(self.options.get("lookback_hours", 6)) * 3600
        now = datetime.now(timezone.utc)

        reset_at = _latest_marker(projects, lookback, now)
        if reset_at is None:
            return QuotaState(Status.AVAILABLE, detail="no usage-limit marker")
        if now >= reset_at:
            return QuotaState(Status.AVAILABLE, detail="limit window elapsed")

        return QuotaState(
            Status.EXHAUSTED,
            reset_at=reset_at,
            detail="usage limit reached (exact reset)",
        )
