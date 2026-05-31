"""Codex provider — zero-cost, local-only refill reading for the OpenAI Codex CLI.

Like the claude_code provider it NEVER calls a remote API. Codex is friendlier
here: its CLI caches the server's own rate-limit snapshot into the session rollout
logs, so when present this reading is AUTHORITATIVE (not a block estimate).

Where Codex writes it:
  ~/.codex/sessions/YYYY/MM/DD/rollout-<...>.jsonl   (override with $CODEX_HOME)
Each line is JSON with a top-level "timestamp". Token-count events embed a
`rate_limits` object with `primary` (the short ~5h window) and `secondary`
(weekly) windows. Current Codex builds write each window's `used_percent` and
absolute `resets_at` epoch; older builds wrote relative `resets_in_seconds`.

We tolerantly scan the most recent rollout for the latest object that contains
either reset field, prefer the `primary` window, and compute:
    reset_at = epoch(resets_at) OR <line timestamp> + resets_in_seconds

When nothing usable is found we return UNKNOWN with a hint to run Codex once or
use a `manual`/`command` provider instead.

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


def _epoch_to_dt(raw: float) -> datetime:
    if raw > 1_000_000_000_000:  # milliseconds
        raw /= 1000
    return datetime.fromtimestamp(raw, tz=timezone.utc)


def _window_reset_at(node: dict, line_ts: datetime) -> datetime | None:
    resets_at = node.get("resets_at")
    if isinstance(resets_at, (int, float)):
        try:
            return _epoch_to_dt(float(resets_at))
        except (OSError, OverflowError, ValueError):
            return None

    resets_in = node.get("resets_in_seconds")
    if isinstance(resets_in, (int, float)):
        return line_ts + timedelta(seconds=float(resets_in))

    return None


def _find_window(obj, prefer: str, line_ts: datetime):
    """Recursively locate a rate-limit window dict.

    Returns (used_percent, reset_at) or None. Prefers a window reached
    via a key named `prefer` (e.g. 'primary'); otherwise falls back to the window
    with the SMALLEST reset (the short rolling window)."""
    best = None       # (used_percent, reset_at)
    preferred = None  # (used_percent, reset_at)

    def visit(node, under_prefer: bool):
        nonlocal best, preferred
        if isinstance(node, dict):
            reset_at = _window_reset_at(node, line_ts)
            if reset_at is not None:
                pct = node.get("used_percent")
                pct = float(pct) if isinstance(pct, (int, float)) else None
                if under_prefer and preferred is None:
                    preferred = (pct, reset_at)
                if best is None or reset_at < best[1]:
                    best = (pct, reset_at)
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
            if not line or ("resets_at" not in line and "resets_in_seconds" not in line):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            line_ts = _parse_ts(obj.get("timestamp")) or datetime.fromtimestamp(
                rollout.stat().st_mtime, tz=timezone.utc
            )
            window = _find_window(obj, prefer, line_ts)
            if window is None:
                continue
            used_percent, reset_at = window
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
            detail="no usable Codex rate-limit snapshot; run codex once or use --reset",
        )
