"""Tests for art module — including new breathing + animated clock."""

from rich.text import Text

from backtowork.art import (
    DIGIT_HEIGHT,
    big_clock,
    big_clock_animated,
    breathing_green,
    big_digits,
    bubbles_frame,
    clock_text,
    spinner,
    wave_text,
)


def test_clock_text():
    assert clock_text(0) == "00:00"
    assert clock_text(65) == "01:05"
    assert clock_text(3725) == "1:02:05"
    assert clock_text(-10) == "00:00"


def test_big_digits_height():
    out = big_digits("12:34")
    lines = out.split("\n")
    assert len(lines) == DIGIT_HEIGHT
    # all rows equal width
    assert len({len(line) for line in lines}) == 1


def test_big_clock_renders():
    assert big_clock(3661).count("\n") == DIGIT_HEIGHT - 1


def test_bubbles_frame_dimensions():
    frame = bubbles_frame(1.5, width=20, height=5)
    lines = frame.split("\n")
    assert len(lines) == 5
    # Strip markup to check plain-text width
    plain_lines = [Text.from_markup(l).plain for l in lines]
    assert all(len(l) == 20 for l in plain_lines)


def test_bubbles_animates():
    # Different time → different frame (motion).
    assert bubbles_frame(0.0) != bubbles_frame(1.0)


def test_bubbles_is_valid_markup():
    """Bubbles output must be parseable Rich markup."""
    for t in (0.0, 0.5, 1.3):
        Text.from_markup(bubbles_frame(t, width=20, height=5))


def test_wave_text_valid_markup_and_animates():
    for t in (0.0, 0.5, 1.3, 2.7):
        # Must be parseable rich markup (raises otherwise).
        Text.from_markup(wave_text("BACK TO WORK", t))
    assert wave_text("BACK", 0.0) != wave_text("BACK", 1.0)


def test_spinner_cycles():
    frames = {spinner(i * 0.1) for i in range(10)}
    assert len(frames) > 1  # actually animates
    assert all(len(s) == 1 for s in frames)


# --- new animation tests ----------------------------------------------------

def test_breathing_green_cycles():
    """breathing_green returns different color names over time."""
    colors = {breathing_green(t * 0.5) for t in range(10)}
    assert len(colors) > 1


def test_breathing_green_is_valid_rich_color():
    """Each returned color should be a known rich color name (non-empty str)."""
    for t in range(20):
        c = breathing_green(t * 0.3)
        assert isinstance(c, str) and len(c) > 0


def test_big_clock_animated_dimensions():
    """animated clock has the right number of rows."""
    animated = big_clock_animated(3661, 0.0)
    rows = animated.split("\n")
    assert len(rows) == DIGIT_HEIGHT
    for row in rows:
        assert len(row) > 0


def test_big_clock_animated_colon_blinks():
    """Colon toggles visible/hidden across time."""
    c_on = big_clock_animated(3661, 0.0)
    c_off = big_clock_animated(3661, 0.6)
    assert c_on != c_off


def test_big_clock_animated_is_valid_markup():
    """Output must be parseable Rich markup (raises otherwise)."""
    for t in (0.0, 0.5, 1.3, 2.7):
        Text.from_markup(big_clock_animated(3661, t))
    # Different times produce different markup (wave moves).
    assert big_clock_animated(3661, 0.0) != big_clock_animated(3661, 1.0)


def test_big_clock_animated_negative_seconds():
    """Negative seconds should render as 00:00."""
    assert big_clock_animated(-1, 0.0) == big_clock_animated(0, 0.0)
