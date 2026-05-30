"""Tiny duration / reset-time parsing shared by the manual provider and the CLI."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

_TOKEN = re.compile(r"(\d+)\s*([hms])", re.IGNORECASE)


def parse_duration(text: str) -> timedelta:
    """Parse a relative duration like '3h', '90m', '2h30m', '45s', '5s'.

    Raises ValueError if nothing parseable is found.
    """
    text = text.strip()
    matches = _TOKEN.findall(text)
    if not matches:
        raise ValueError(f"could not parse duration: {text!r}")
    # Reject leftover junk (e.g. '3x') so typos surface instead of silently passing.
    if _TOKEN.sub("", text).strip():
        raise ValueError(f"could not parse duration: {text!r}")

    seconds = 0
    for value, unit in matches:
        unit = unit.lower()
        n = int(value)
        if unit == "h":
            seconds += n * 3600
        elif unit == "m":
            seconds += n * 60
        else:  # "s"
            seconds += n
    return timedelta(seconds=seconds)


def resolve_reset(text: str, *, now: datetime | None = None) -> datetime:
    """Turn a user string into an absolute UTC reset time.

    Accepts either an absolute ISO-8601 timestamp ('2026-05-30T18:00:00Z') or a
    relative duration ('3h', '90m', '2h30m'). Naive datetimes are treated as UTC.
    """
    now = now or datetime.now(timezone.utc)
    text = text.strip()

    # Try absolute ISO first.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass

    return now + parse_duration(text)
