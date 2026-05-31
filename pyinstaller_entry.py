"""PyInstaller entry point. Frozen builds run this; it just calls the CLI.

We patch sys.stdout/stderr to UTF-8 HERE — before any module import — so that
when rich later reads sys.stdout it sees a UTF-8 stream and never falls back to
the legacy Windows console renderer (which encodes via cp1252 and can't handle
our box-art glyphs). This is the only reliable place to do this in a frozen exe.
"""

import io
import sys

if sys.platform == "win32":
    for _attr in ("stdout", "stderr"):
        _stream = getattr(sys, _attr, None)
        if _stream is not None and hasattr(_stream, "buffer"):
            try:
                setattr(
                    sys,
                    _attr,
                    io.TextIOWrapper(
                        _stream.buffer,
                        encoding="utf-8",
                        errors="replace",
                        line_buffering=True,
                    ),
                )
            except Exception:
                pass
    # Also flip the console code page to UTF-8 so the underlying buffer
    # accepts the bytes we write.
    try:
        import ctypes
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:
        pass

from backtowork.cli import main  # noqa: E402 — must come after stdout patch

if __name__ == "__main__":
    sys.exit(main())
