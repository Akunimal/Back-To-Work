"""Claude Code provider — zero-cost, local-only refill estimate.

It NEVER calls the Anthropic API (that would burn usage). Instead it reads Claude
Code's own session transcripts on disk and estimates the rolling 5-hour usage
block, the same way community tools like `ccusage` do.

How it works:
  - Claude Code writes one JSONL transcript per session under
    ~/.claude/projects/**/*.jsonl. Every line carries an ISO-8601 "timestamp".
  - Anthropic usage runs in 5-hour blocks that begin at the hour of the first
    message. A gap longer than the block length starts a fresh block.
  - So the current block's refill time is roughly:  block_start + 5h.

This is an ESTIMATE of the block boundary, not a live quota reading. When you
hit the limit before the block ends, override with `backtowork watch --reset <when>`
or a `command` provider. See README.

Options (all optional):
    block_hours   = 5      # length of the usage block
    idle_minutes  = 300    # no activity for this long -> consider the window fresh
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import QuotaState, Status
from .base import Provider, register

_TS = re.compile(r'"timestamp"\s*:\s*"([^"]+)"')


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


def _parse_ts(raw: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _floor_to_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _collect_timestamps(projects: Path, window: timedelta, now: datetime) -> list[datetime]:
    """Gather recent timestamps cheaply: skip files untouched within the window,
    then regex-scan the rest (no per-line JSON parse)."""
    cutoff = now - window
    stamps: list[datetime] = []
    for jsonl in projects.rglob("*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(jsonl.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if mtime < cutoff:
            continue
        try:
            text = jsonl.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for m in _TS.findall(text):
            ts = _parse_ts(m)
            if ts is not None and ts >= cutoff:
                stamps.append(ts)
    stamps.sort()
    return stamps


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

        block = timedelta(hours=float(self.options.get("block_hours", 5)))
        idle = timedelta(minutes=float(self.options.get("idle_minutes", 300)))
        now = datetime.now(timezone.utc)

        # Look back two blocks so we can find the start of the current cluster.
        stamps = _collect_timestamps(projects, window=2 * block, now=now)
        if not stamps:
            return QuotaState(Status.AVAILABLE, detail="no recent activity")

        latest = stamps[-1]
        if now - latest > idle:
            return QuotaState(Status.AVAILABLE, detail="idle; window is fresh")

        # Walk backward to the start of the current contiguous block: stop at the
        # first gap longer than one block length.
        block_start = latest
        for prev in reversed(stamps[:-1]):
            if block_start - prev > block:
                break
            block_start = prev

        reset_at = _floor_to_hour(block_start) + block
        if now >= reset_at:
            return QuotaState(Status.AVAILABLE, detail="block elapsed")

        return QuotaState(
            Status.EXHAUSTED,
            reset_at=reset_at,
            detail="5h block (estimate) · --reset to override",
        )
