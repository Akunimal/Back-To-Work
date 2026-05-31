from rich.text import Text

from backtowork.art import (
    DIGIT_HEIGHT,
    big_clock,
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
    assert all(len(line) == 20 for line in lines)


def test_bubbles_animates():
    # Different time → different frame (motion).
    assert bubbles_frame(0.0) != bubbles_frame(1.0)


def test_wave_text_valid_markup_and_animates():
    for t in (0.0, 0.5, 1.3, 2.7):
        # Must be parseable rich markup (raises otherwise).
        Text.from_markup(wave_text("BACK TO WORK", t))
    assert wave_text("BACK", 0.0) != wave_text("BACK", 1.0)


def test_spinner_cycles():
    frames = {spinner(i * 0.1) for i in range(10)}
    assert len(frames) > 1  # actually animates
    assert all(len(s) == 1 for s in frames)
