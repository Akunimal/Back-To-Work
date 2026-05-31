"""Codex provider — zero-cost, local-only refill reading for the OpenAI Codex CLI.

Like the claude_code provider it NEVER calls a remote API. Codex is friendlier
here: its CLI caches the server's own rate-limit snapshot into the session rollout
logs, so when present this reading is AUTHORITATIVE (not a block estimate).

Where Codex writes it:
  ~/.codex/sessions/YYYY/MM/DD/rollout-<...>.jsonl   (override with $CODEX_HOME)
Each line is JSON with a top-level "timestamp". Token-count events embed a
`rate_limits` object with `primary` (the short ~5h window) and `secondary`
(weekly) windows, each carrying `used_percent` and `resets_in_seconds`.

We tolerantly scan the most recent rollout for the latest object that contains
`resets_in_seconds`, prefer the `primary` window, and compute:
    reset_at = <line timestamp> + resets_in_seconds

Note: some Codex versions log `rate_limits` as null until the server sends a
snapshot (see openai/codex#14880). When nothing usable is found we return
UNKNOWN with a hint to use a `manual`/`command` provider instead.

Options (all optional):
    threshold_percent = 95          # treat the window as exhausted at/above this
    window            = "primary"   # or "secondary" (weekly)
    max_age_days      = 14          # ignore rollout files older than this
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import QuotaState, Status
from .base import Provider, register


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def _parse_ts(raw) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _find_window(obj, prefer: str):
    """Recursively locate a rate-limit window dict (one with 'resets_in_seconds').

    Returns (used_percent, resets_in_seconds) or None. Prefers a window reached
    via a key named `prefer` (e.g. 'primary'); otherwise falls back to the window
    with the SMALLEST reset (the short rolling window)."""
    best = None       # (used_percent, resets_in_seconds)
    preferred = None  # (used_percent, resets_in_seconds)

    def visit(node, under_prefer: bool):
        nonlocal best, preferred
        if isinstance(node, dict):
            secs_raw = node.get("resets_in_seconds")
            if isinstance(secs_raw, (int, float)):
                pct = node.get("used_percent")
                pct = float(pct) if isinstance(pct, (int, float)) else None
                secs = float(secs_raw)
                if under_prefer and preferred is None:
                    preferred = (pct, secs)
                if best is None or secs < best[1]:
                    best = (pct, secs)
            for k, v in node.items():
                visit(v, under_prefer or k == prefer)
        elif isinstance(node, list):
            for v in node:
                visit(v, under_prefer)

    visit(obj, False)
    return preferred if preferred is not None else best


def _latest_rollout(home: Path, max_age: timedelta, now: datetime) -> Path | None:
    sessions = home / "sessions"
    if not sessions.exists():
        return None
    newest: tuple[float, Path] | None = None
    cutoff = (now - max_age).timestamp()
    for jsonl in sessions.rglob("*.jsonl"):
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        if newest is None or mtime > newest[0]:
            newest = (mtime, jsonl)
    return newest[1] if newest else None


@register("codex")
class CodexProvider(Provider):
    def read_state(self) -> QuotaState:
        home = _codex_home()
        if not home.exists():
            return QuotaState(
                Status.UNKNOWN,
                detail=f"{home} not found; is the Codex CLI installed here?",
            )

        prefer = str(self.options.get("window", "primary"))
        threshold = float(self.options.get("threshold_percent", 95))
        max_age = timedelta(days=float(self.options.get("max_age_days", 14)))
        now = datetime.now(timezone.utc)

        rollout = _latest_rollout(home, max_age, now)
        if rollout is None:
            return QuotaState(
                Status.UNKNOWN,
                detail="no recent Codex session logs; run codex once to record usage",
            )

        try:
            lines = rollout.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError as exc:
            return QuotaState(Status.UNKNOWN, detail=f"cannot read {rollout.name}: {exc}")

        # Scan from the end for the most recent line carrying a rate-limit window.
        for line in reversed(lines):
            line = line.strip()
            if not line or "resets_in_seconds" not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            window = _find_window(obj, prefer)
            if window is None:
                continue
            used_percent, resets_in = window
            line_ts = _parse_ts(obj.get("timestamp")) or datetime.fromtimestamp(
                rollout.stat().st_mtime, tz=timezone.utc
            )
            reset_at = line_ts + timedelta(seconds=resets_in)
            pct_used = (used_percent / 100.0) if used_percent is not None else None

            if now >= reset_at:
                return QuotaState(Status.AVAILABLE, pct_used=pct_used, detail="window reset")
            if used_percent is not None and used_percent >= threshold:
                return QuotaState(
                    Status.EXHAUSTED,
                    reset_at=reset_at,
                    pct_used=pct_used,
                    detail=f"{prefer} window {used_percent:.0f}% used",
                )
            return QuotaState(
                Status.AVAILABLE,
                pct_used=pct_used,
                detail=(
                    f"{prefer} window {used_percent:.0f}% used"
                    if used_percent is not None
                    else "credit available"
                ),
            )

        return QuotaState(
            Status.UNKNOWN,
            detail="Codex doesn't save reset time locally (upstream bug #14880) — "
            "use --reset for an exact countdown",
        )
