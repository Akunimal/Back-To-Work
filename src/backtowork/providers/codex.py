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
either reset field, read both quota windows, and compute:
    reset_at = epoch(resets_at) OR <line timestamp> + resets_in_seconds

When nothing usable is found we return UNKNOWN with a hint to run Codex once or
use a `manual`/`command` provider instead.

Options (all optional):
    threshold_percent = 95          # treat the window as exhausted at/above this
    window            = "primary"   # legacy main window for pct_used/reset_at
    max_age_days      = 14          # ignore rollout files older than this
"""

from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..models import QuotaState, Status, UsageWindow
from .base import Provider, register

# The short rolling quota window Codex reports as `primary` is ~5h. If our newest
# on-disk snapshot is older than that, every percentage in it predates a full
# refill cycle and must be treated as a guess, not a live reading.
_PRIMARY_WINDOW = timedelta(minutes=300)


def _codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))


def _age_label(age: timedelta) -> str:
    secs = max(0, int(age.total_seconds()))
    h, rem = divmod(secs, 3600)
    if h >= 24:
        return f"{h // 24}d{(h % 24):02d}h"
    m = rem // 60
    return f"{h}h{m:02d}m" if h else f"{m}m"


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


def _window_from_node(name: str, node, line_ts: datetime) -> UsageWindow | None:
    if not isinstance(node, dict):
        return None
    reset_at = _window_reset_at(node, line_ts)
    pct = node.get("used_percent")
    pct_used = (float(pct) / 100.0) if isinstance(pct, (int, float)) else None
    # A window with neither a reset nor a percentage carries no signal. But a
    # window with a percentage and no reset (e.g. a plan that omits the weekly
    # reset epoch) is still worth showing — just without a countdown.
    if reset_at is None and pct_used is None:
        return None
    label = "current" if name == "primary" else "weekly" if name == "secondary" else name
    return UsageWindow(
        name=label,
        pct_used=pct_used,
        reset_at=reset_at,
        detail=f"{int(node.get('window_minutes', 0))}m window"
        if isinstance(node.get("window_minutes"), int)
        else None,
    )


def _extract_windows(rate_limits: dict, line_ts: datetime) -> tuple[UsageWindow, ...]:
    windows: list[UsageWindow] = []
    for name in ("primary", "secondary"):
        window = _window_from_node(name, rate_limits.get(name), line_ts)
        if window is not None:
            windows.append(window)
    return tuple(windows)


def _recent_rollouts(home: Path, max_age: timedelta, now: datetime) -> list[Path]:
    sessions = home / "sessions"
    if not sessions.exists():
        return []
    cutoff = (now - max_age).timestamp()
    rollouts: list[tuple[float, Path]] = []
    for jsonl in sessions.rglob("*.jsonl"):
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        rollouts.append((mtime, jsonl))
    rollouts.sort(reverse=True)
    return [path for _, path in rollouts]


def _finalize_window(
    w: UsageWindow, now: datetime, threshold: float, stale: bool
) -> UsageWindow:
    """Tag a raw window with a per-window status, normalize spent windows, and
    flag stale percentages so the UI never presents a guess as a live reading."""
    # Window already past its reset → it has refilled. The stale percentage we
    # last saw is meaningless now; show it as available with no countdown.
    if w.reset_at is not None and now >= w.reset_at:
        return replace(
            w,
            pct_used=0.0,
            reset_at=None,
            detail="reset — run codex to refresh",
            status=Status.AVAILABLE,
            assumed=True,
        )
    status = Status.AVAILABLE
    if w.pct_used is not None and w.pct_used * 100 >= threshold:
        status = Status.EXHAUSTED
    detail = w.detail
    if stale:
        detail = f"{detail} · stale" if detail else "stale"
    return replace(w, detail=detail, status=status, assumed=stale)


def _apply_reached(
    windows: tuple[UsageWindow, ...], reached_type
) -> tuple[UsageWindow, ...]:
    """Honor Codex's authoritative `rate_limit_reached_type`: if the server says
    a window is blocked, mark it exhausted even if its percentage sits below our
    local threshold."""
    target = {"primary": "current", "secondary": "weekly"}.get(reached_type)
    if target is None:
        return windows
    return tuple(
        replace(w, status=Status.EXHAUSTED)
        if w.name == target and w.reset_at is not None
        else w
        for w in windows
    )


def _latest_snapshot(home: Path, max_age: timedelta, now: datetime, prefer: str):
    """Return the newest usable Codex rate-limit snapshot across recent rollouts."""
    best: tuple[
        datetime,
        float | None,
        datetime,
        tuple[UsageWindow, ...],
        object,
        object,
    ] | None = None

    for rollout in _recent_rollouts(home, max_age, now):
        try:
            lines = rollout.read_text(encoding="utf-8", errors="ignore").splitlines()
            fallback_ts = datetime.fromtimestamp(rollout.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue

        for line in reversed(lines):
            line = line.strip()
            if (
                not line
                or "rate_limits" not in line
                or ("resets_at" not in line and "resets_in_seconds" not in line)
            ):
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            line_ts = _parse_ts(obj.get("timestamp")) or fallback_ts
            rate_limits = None
            if isinstance(obj, dict):
                payload = obj.get("payload")
                if isinstance(payload, dict):
                    rate_limits = payload.get("rate_limits")
                rate_limits = rate_limits or obj.get("rate_limits")
            if not isinstance(rate_limits, dict):
                continue
            window = _find_window(rate_limits, prefer, line_ts)
            if window is None:
                continue
            used_percent, reset_at = window
            usage_windows = _extract_windows(rate_limits, line_ts)
            reached = rate_limits.get("rate_limit_reached_type")
            plan = rate_limits.get("plan_type")
            if best is None or line_ts > best[0]:
                best = (line_ts, used_percent, reset_at, usage_windows, reached, plan)
            break

    return best


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

        snapshot = _latest_snapshot(home, max_age, now, prefer)
        if snapshot is None:
            return QuotaState(
                Status.UNKNOWN,
                detail="no usable Codex rate-limit snapshot; run codex once",
            )

        snapshot_ts, used_percent, reset_at, raw_windows, reached_type, plan_type = snapshot
        # A snapshot older than one full primary window predates a refill cycle;
        # its percentages are guesses, not live readings.
        age = now - snapshot_ts
        stale = age > _PRIMARY_WINDOW

        windows = tuple(_finalize_window(w, now, threshold, stale) for w in raw_windows)
        windows = _apply_reached(windows, reached_type)

        plan_note = f" · {plan_type}" if isinstance(plan_type, str) and plan_type else ""
        exhausted = [w for w in windows if w.status == Status.EXHAUSTED]

        if exhausted:
            reset_candidates = [w.reset_at for w in exhausted if w.reset_at is not None]
            detail = ", ".join(
                f"{w.name} {w.pct_used * 100:.0f}% used"
                for w in exhausted
                if w.pct_used is not None
            )
            return QuotaState(
                Status.EXHAUSTED,
                reset_at=min(reset_candidates) if reset_candidates else reset_at,
                pct_used=(used_percent / 100.0) if used_percent is not None else None,
                detail=(detail or "limit reached") + plan_note,
                usage_windows=windows,
            )

        if stale:
            # Nothing on disk is recent enough to assert a confident "100% free".
            # Surface the uncertainty instead of a misleading full battery.
            return QuotaState(
                Status.AVAILABLE,
                pct_used=None,
                detail=f"stale snapshot ({_age_label(age)} old) — run codex to confirm" + plan_note,
                usage_windows=windows,
            )

        primary = next((w for w in windows if w.name == "current"), None)
        pct_used = (
            primary.pct_used
            if primary is not None
            else (used_percent / 100.0) if used_percent is not None else None
        )
        detail = (
            f"current window {primary.pct_used * 100:.0f}% used"
            if primary is not None and primary.pct_used is not None
            else "credit available"
        )
        return QuotaState(
            Status.AVAILABLE,
            pct_used=pct_used,
            detail=detail + plan_note,
            usage_windows=windows,
        )
