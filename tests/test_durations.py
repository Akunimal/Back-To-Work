from datetime import datetime, timedelta, timezone

import pytest

from backtowork.durations import parse_duration, resolve_reset


def test_parse_simple_units():
    assert parse_duration("3h") == timedelta(hours=3)
    assert parse_duration("90m") == timedelta(minutes=90)
    assert parse_duration("45s") == timedelta(seconds=45)


def test_parse_compound():
    assert parse_duration("2h30m") == timedelta(hours=2, minutes=30)
    assert parse_duration("1h2m3s") == timedelta(hours=1, minutes=2, seconds=3)


def test_parse_rejects_junk():
    for bad in ("", "soon", "3x", "3h banana"):
        with pytest.raises(ValueError):
            parse_duration(bad)


def test_resolve_relative():
    now = datetime(2026, 5, 30, 12, 0, tzinfo=timezone.utc)
    assert resolve_reset("3h", now=now) == now + timedelta(hours=3)


def test_resolve_absolute_iso():
    got = resolve_reset("2026-05-30T18:00:00Z")
    assert got == datetime(2026, 5, 30, 18, 0, tzinfo=timezone.utc)


def test_resolve_naive_iso_treated_as_utc():
    got = resolve_reset("2026-05-30T18:00:00")
    assert got.tzinfo == timezone.utc
