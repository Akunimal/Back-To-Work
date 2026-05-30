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
_BUBBLE_CHARS = " ·∘oO"


def bubbles_frame(t: float, width: int = 28, height: int = 6) -> str:
    """A frame of dots rising like bubbles. `t` is a monotonically rising time
    (seconds). Deterministic, so it animates smoothly across calls."""
    grid = [[" "] * width for _ in range(height)]
    for col in range(0, width, 3):
        phase = (t * (0.7 + 0.25 * (col % 5)) + col * 0.9) % (height + 2)
        row = height - 1 - int(phase)
        if 0 <= row < height:
            size = 1 + int((math.sin(t * 1.3 + col) + 1) * 1.9)  # 1..4
            grid[row][col] = _BUBBLE_CHARS[min(size, len(_BUBBLE_CHARS) - 1)]
    return "\n".join("".join(r) for r in grid)
