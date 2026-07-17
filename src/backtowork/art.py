"""ASCII art: the LOGO, the celebration banner, a battery bar, a Commodore-style
big-digit clock, and a bubbles animation for the live watch view.

If you want big figlet letters elsewhere, `pip install pyfiglet`.
"""

from __future__ import annotations

import math

LOGO = r"""
   ╭──────────────────────────────────╮
   │  back to work  ·  ⏳ watching...  │
   ╰──────────────────────────────────╯
""".strip("\n")


CELEBRATION = r"""
   ╔══════════════════════════════════════════════╗
   ║                                                ║
   ║   ⚡   B A C K   T O   W O R K   ⚡             ║
   ║                                                ║
   ║              [██████████████████]  100%        ║
   ║                                                ║
   ╚══════════════════════════════════════════════╝
""".strip("\n")


def battery(pct_used: float | None) -> str:
    """A 10-cell battery bar from a 0..1 *used* fraction."""
    if pct_used is None:
        return "[··········]    ?%"
    pct_used = max(0.0, min(1.0, pct_used))
    remaining = 1.0 - pct_used
    cells = round(remaining * 10)
    # A full 10-cell bar must mean truly zero usage — otherwise a 1%-used window
    # rounds up to a full battery and reads as a false 100%.
    if pct_used > 0 and cells == 10:
        cells = 9
    return "[" + "█" * cells + "·" * (10 - cells) + f"] {remaining * 100:3.0f}%"


# --- Commodore-style big digits ---------------------------------------------
# Each glyph is 3 wide x 5 tall. Rendered green by the caller for the CRT vibe.
_FONT: dict[str, list[str]] = {
    "0": ["███", "█ █", "█ █", "█ █", "███"],
    "1": [" █ ", "██ ", " █ ", " █ ", "███"],
    "2": ["███", "  █", "███", "█  ", "███"],
    "3": ["███", "  █", "███", "  █", "███"],
    "4": ["█ █", "█ █", "███", "  █", "  █"],
    "5": ["███", "█  ", "███", "  █", "███"],
    "6": ["███", "█  ", "███", "█ █", "███"],
    "7": ["███", "  █", "  █", "  █", "  █"],
    "8": ["███", "█ █", "███", "█ █", "███"],
    "9": ["███", "█ █", "███", "  █", "███"],
    ":": ["   ", " █ ", "   ", " █ ", "   "],
    " ": ["   ", "   ", "   ", "   ", "   "],
}

DIGIT_HEIGHT = 5


def big_digits(text: str) -> str:
    """Render text (digits, ':' and spaces) as a 5-row block-glyph banner."""
    glyphs = [_FONT.get(ch, _FONT[" "]) for ch in text]
    rows = []
    for r in range(DIGIT_HEIGHT):
        rows.append(" ".join(g[r] for g in glyphs))
    return "\n".join(rows)


def clock_text(seconds: int) -> str:
    """Format a countdown as H:MM:SS (drops the hour when zero)."""
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def big_clock(seconds: int) -> str:
    """The big green countdown the watch view shows while waiting."""
    return big_digits(clock_text(seconds))


# --- bubbles animation (fallback / idle flourish) ----------------------------
_BUBBLE_CHARS = "·∘oO"


def bubbles_frame(t: float, width: int = 28, height: int = 6) -> str:
    """Animated particle system — rising bubbles with lateral sway + per-char colour wave.
    Returns Rich markup so each particle gets its own green shade,
    creating a subtle shimmer across the bubble field."""
    grid = [[" "] * width for _ in range(height)]
    # Background mist — slow tiny dots at every column
    for col in range(width):
        phase = (t * 0.35 + col * 0.45) % (height + 2)
        row = height - 1 - int(phase)
        if 0 <= row < height:
            bright = (math.sin(t * 0.7 + col * 0.5) + 1) * 0.5
            if bright > 0.65:
                grid[row][col] = "·"
    # Foreground bubbles — every 2nd column with lateral sway
    for col in range(0, width, 2):
        phase = (t * (0.65 + 0.3 * (col % 5)) + col * 0.85) % (height + 2)
        row = height - 1 - int(phase)
        if 0 <= row < height:
            sway = int(math.sin(t * 1.3 + col * 0.6) * 0.8)
            cx = max(0, min(width - 1, col + sway))
            size = int((math.sin(t * 1.6 + col) + 1) * 2)  # 0..3
            grid[row][cx] = _BUBBLE_CHARS[min(size, len(_BUBBLE_CHARS) - 1)]
    # Convert to Rich markup with per-character green wave
    palette = _BREATHING_GREENS
    speed = 3.0
    rows = []
    for r in range(height):
        raw = grid[r]
        segments = []
        seg_text = ""
        seg_color = ""
        for col, ch in enumerate(raw):
            if ch == " ":
                if seg_text:
                    segments.append((seg_text, seg_color))
                    seg_text = ""
                segments.append((" ", ""))
                continue
            idx = int(t * speed + col + r * width) % len(palette)
            color = palette[idx]
            if color == seg_color:
                seg_text += ch
            else:
                if seg_text:
                    segments.append((seg_text, seg_color))
                seg_text = ch
                seg_color = color
        if seg_text:
            segments.append((seg_text, seg_color))
        row_parts = []
        for seg_text, seg_color in segments:
            if seg_color:
                row_parts.append(f"[" + seg_color + "]" + seg_text + "[/]")
            else:
                row_parts.append(seg_text)
        rows.append("".join(row_parts))
    return "\n".join(rows)


# --- animated title shimmer (Commodore CRT vibe) -----------------------------
# A green wave moves across the letters frame to frame.
_SHIMMER = ["green", "green3", "spring_green2", "bright_green", "spring_green2", "green3"]


def wave_text(text: str, t: float, palette: list[str] | None = None) -> str:
    """Rich markup for `text` with a green shimmer wave moving across it.

    Render with `rich.text.Text.from_markup(...)`. Deterministic in `t` so it
    animates smoothly. Brackets in `text` are dropped to keep markup valid."""
    palette = palette or _SHIMMER
    n = len(palette)
    speed = 5.0
    out = []
    for i, ch in enumerate(text):
        if ch in " []":
            out.append(" " if ch == " " else "")
            continue
        idx = int(t * speed + i) % n
        out.append(f"[bold {palette[idx]}]{ch}[/]")
    return "".join(out)


_SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def spinner(t: float) -> str:
    """A single braille spinner glyph for the current frame."""
    return _SPINNER[int(t * 10) % len(_SPINNER)]

# --- breathing clock effects -------------------------------------------------

_BREATHING_GREENS = [
    "green", "green3", "spring_green2", "bright_green",
    "spring_green2", "green3",
]


def breathing_green(t: float) -> str:
    """Returns a green shade that cycles smoothly frame-to-frame."""
    return _BREATHING_GREENS[int(t * 2.5) % len(_BREATHING_GREENS)]


# Empty colon variant so the big clock blinks
_EMPTY_COLON = ["   ", "   ", "   ", "   ", "   "]

def big_clock_animated(seconds: int, t: float) -> str:
    """Big clock digits with per-character color wave + blinking colon.

    Returns Rich markup so each block glyph gets its own green shade,
    creating a travelling wave across the countdown (like the Copilot CLI
    banner approach of per-character color roles).
    """
    text = clock_text(seconds)
    glyphs = [_FONT.get(ch, _FONT[" "]) for ch in text]
    colon_visible = int(t * 2) % 2 == 0
    palette = _BREATHING_GREENS
    speed = 4.0
    rows = []
    for r in range(DIGIT_HEIGHT):
        raw_chars = []
        for i, (ch, glyph) in enumerate(zip(text, glyphs)):
            if ch == ":" and not colon_visible:
                raw_chars.extend(list(_EMPTY_COLON[r]))
            else:
                raw_chars.extend(list(glyph[r]))
            if i < len(text) - 1:
                raw_chars.append(" ")  # inter-glyph space (same as " ".join in big_digits)
        # Build segments — consecutive chars with same color
        segments = []
        seg_text = ""
        seg_color = ""
        for col, ch in enumerate(raw_chars):
            idx = int(t * speed + col) % len(palette)
            color = palette[idx]
            if color == seg_color:
                seg_text += ch
            else:
                if seg_text:
                    segments.append((seg_text, seg_color))
                seg_text = ch
                seg_color = color
        if seg_text:
            segments.append((seg_text, seg_color))
        # Render as Rich markup
        row_parts = []
        for seg_text, seg_color in segments:
            if seg_text.strip():
                row_parts.append(f"[bold {seg_color}]{seg_text}[/]")
            else:
                row_parts.append(seg_text)  # spaces = no markup
        rows.append("".join(row_parts))
    return "\n".join(rows)
