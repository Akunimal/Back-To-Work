"""Claude Code provider — zero-cost, local-only, EXACT limit detection.

It NEVER calls the Anthropic API (that would burn usage). Instead it reads Claude
Code's own session transcripts on disk and looks for the explicit usage-limit
marker the CLI writes when it actually gets rate-limited.

How it works:
  - Claude Code writes one JSONL transcript per session under
    ~/.claude/projects/**/*.jsonl.
  - When (and only when) you hit the rolling usage limit, Claude Code records a
    real API error message such as:
      `You've hit your session limit · resets 5pm (America/Buenos_Aires)`
    Older builds may write:
      `Claude Code usage limit reached|<unix_epoch>`
  - We scan recent transcripts for those messages and report the most recent one.
    If its reset time is still in the future -> EXHAUSTED with the exact reset.
    If the marker elapsed -> AVAILABLE. If no marker is present -> UNKNOWN.

This is EXACT (not a 5-hour estimate): the reset time comes straight from the
marker Claude Code itself wrote. No API call, no guessing from activity.

Key fix vs. older versions: having recent activity does NOT mean you're out of
credit, but no marker also does not prove credit is available.

Options (all optional):
    lookback_hours = 6     # only scan transcripts touched within this window
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

from ..models import QuotaState, Status
from .base import Provider, register

# The marker Claude Code writes on a real rate-limit, e.g.
#   Claude Code usage limit reached|1748736000
# Be liberal: match the phrase followed by a pipe and a 10–13 digit epoch.
_MARKER = re.compile(r"usage limit reached\|(\d{10,13})", re.IGNORECASE)
_RESETS = re.compile(r"\bresets?\s+(.+?)(?:\s*\(([^)]+)\))?$", re.IGNORECASE)
_SPANISH_RESETS = re.compile(
    r"\brestablece\s+a\s+las\s+(.+?)(?:\s*\(([^)]+)\))?$", re.IGNORECASE
)
_TIME = re.compile(r"^(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)$", re.IGNORECASE)
_MONTHS = {
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
}
_WEEKDAYS = {
    "mon": 0,
    "monday": 0,
    "tue": 1,
    "tuesday": 1,
    "wed": 2,
    "wednesday": 2,
    "thu": 3,
    "thursday": 3,
    "fri": 4,
    "friday": 4,
    "sat": 5,
    "saturday": 5,
    "sun": 6,
    "sunday": 6,
}


def _claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude"))


def _epoch_to_dt(raw: str) -> datetime:
    val = int(raw)
    if val > 1_000_000_000_000:  # milliseconds
        val //= 1000
    return datetime.fromtimestamp(val, tz=timezone.utc)


def _parse_transcript_ts(raw) -> datetime | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _tz(name: str | None):
    if not name:
        return timezone.utc
    normalized = name.strip()
    if normalized.upper() == "UTC":
        return timezone.utc
    if normalized == "America/Buenos_Aires":
        return timezone(timedelta(hours=-3), normalized)
    return timezone.utc


def _parse_time(raw: str) -> time | None:
    cleaned = raw.strip().lower().replace(" ", "")
    cleaned = cleaned.replace("a.m.", "am").replace("p.m.", "pm")
    cleaned = cleaned.replace("a.m", "am").replace("p.m", "pm")
    m = _TIME.match(cleaned)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or "0")
    suffix = m.group(3).replace(".", "")
    if hour < 1 or hour > 12 or minute > 59:
        return None
    if suffix.startswith("p") and hour != 12:
        hour += 12
    elif suffix.startswith("a") and hour == 12:
        hour = 0
    return time(hour, minute)


def _parse_reset_phrase(raw: str, tz_name: str | None, base: datetime) -> datetime | None:
    phrase = raw.strip().rstrip(".")
    zone = _tz(tz_name)
    base_local = base.astimezone(zone)

    parts = phrase.split(None, 1)
    if len(parts) == 2 and parts[0].lower().rstrip(",") in _WEEKDAYS:
        target_day = _WEEKDAYS[parts[0].lower().rstrip(",")]
        reset_time = _parse_time(parts[1])
        if reset_time is None:
            return None
        days = (target_day - base_local.weekday()) % 7
        candidate = datetime.combine(
            base_local.date() + timedelta(days=days), reset_time, tzinfo=zone
        )
        if candidate <= base_local:
            candidate += timedelta(days=7)
        return candidate.astimezone(timezone.utc)

    month_match = re.match(
        r"^([A-Za-z]+)\s+(\d{1,2}),?\s+(.+)$",
        phrase,
        flags=re.IGNORECASE,
    )
    if month_match:
        month = _MONTHS.get(month_match.group(1).lower())
        day = int(month_match.group(2))
        reset_time = _parse_time(month_match.group(3))
        if month is None or reset_time is None:
            return None
        candidate = datetime(
            base_local.year,
            month,
            day,
            reset_time.hour,
            reset_time.minute,
            tzinfo=zone,
        )
        if candidate <= base_local - timedelta(days=180):
            candidate = candidate.replace(year=candidate.year + 1)
        return candidate.astimezone(timezone.utc)

    reset_time = _parse_time(phrase)
    if reset_time is None:
        return None
    candidate = datetime.combine(base_local.date(), reset_time, tzinfo=zone)
    if candidate <= base_local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def _extract_reset(text: str, base: datetime) -> datetime | None:
    marker = _MARKER.search(text)
    if marker:
        try:
            return _epoch_to_dt(marker.group(1))
        except (ValueError, OverflowError, OSError):
            return None

    for regex in (_RESETS, _SPANISH_RESETS):
        m = regex.search(text)
        if m:
            return _parse_reset_phrase(m.group(1), m.group(2), base)
    return None


def _message_text(obj: dict[str, Any]) -> str:
    """Return user-visible text content, excluding tool use/results.

    Claude transcripts also store tool calls and tool outputs. Those can contain
    source code, docs, or this app's own tests mentioning the marker string; they
    must not count as actual CLI limit markers.
    """
    msg = obj.get("message")
    content = msg.get("content") if isinstance(msg, dict) else obj.get("content")
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    chunks: list[str] = []
    for item in content:
        if not isinstance(item, dict) or item.get("type") != "text":
            continue
        text = item.get("text")
        if isinstance(text, str):
            chunks.append(text)
    return "\n".join(chunks)


def _latest_marker(projects: Path, lookback_secs: float, now: datetime) -> datetime | None:
    """Return the reset time from the most recently written usage-limit message
    across recent transcripts, or None if none found."""
    cutoff = now.timestamp() - lookback_secs
    best_seen_at: datetime | None = None
    best_reset: datetime | None = None

    for jsonl in projects.rglob("*.jsonl"):
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            continue
        try:
            lines = jsonl.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        matches: list[tuple[datetime, datetime]] = []
        for line in lines:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                text = _message_text(obj)
                is_real_limit = obj.get("error") == "rate_limit" or bool(
                    obj.get("isApiErrorMessage")
                )
                if not is_real_limit and not _MARKER.search(text):
                    continue
                base = _parse_transcript_ts(obj.get("timestamp")) or now
                reset = _extract_reset(text, base)
                if reset is not None:
                    matches.append((base, reset))
        if not matches:
            continue
        seen_at, reset = max(matches, key=lambda pair: pair[0])
        if best_seen_at is None or seen_at > best_seen_at:
            best_seen_at = seen_at
            best_reset = reset

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
            return QuotaState(Status.UNKNOWN, detail="no usage-limit marker")
        if now >= reset_at:
            return QuotaState(Status.AVAILABLE, detail="limit window elapsed")

        return QuotaState(
            Status.EXHAUSTED,
            reset_at=reset_at,
            detail="usage limit reached (exact reset)",
        )
