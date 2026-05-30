"""Dev-only: generate the bundled refill chime at src/backtowork/sounds/refill.wav.

A short, friendly two-note arpeggio (C6 -> E6 -> G6) with a soft fade so it
doesn't clip. Pure stdlib, no runtime dependency. Run:

    uv run python scripts/gen_sound.py
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 44100
AMP = 0.45


def _tone(freq: float, dur: float) -> list[float]:
    n = int(RATE * dur)
    out = []
    for i in range(n):
        t = i / RATE
        # quick attack, gentle decay so notes don't click
        env = min(1.0, t / 0.01) * math.exp(-3.0 * t / dur)
        out.append(AMP * env * math.sin(2 * math.pi * freq * t))
    return out


def main() -> None:
    notes = [(1046.50, 0.16), (1318.51, 0.16), (1567.98, 0.30)]  # C6 E6 G6
    samples: list[float] = []
    for freq, dur in notes:
        samples.extend(_tone(freq, dur))

    out_path = Path(__file__).resolve().parents[1] / "src" / "backtowork" / "sounds" / "refill.wav"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(out_path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = b"".join(
            struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32767)) for s in samples
        )
        w.writeframes(frames)
    print(f"wrote {out_path} ({out_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
