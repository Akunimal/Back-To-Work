"""Desktop notifier: plays a sound and shows a native toast when credit is back.

Windows is the primary target (sound via the stdlib `winsound`, toast via the
optional `winotify` package). macOS and Linux get best-effort fallbacks. No
PowerShell is used anywhere.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import time
from importlib import resources
from pathlib import Path

from ..models import RefillEvent
from .base import Notifier

_TITLE = "Back To Work"


def _bundled_sound() -> Path | None:
    """Path to the packaged refill sound, or None if it isn't present."""
    try:
        sounds = resources.files("backtowork") / "sounds"
        for name in ("BTWEOTT.mp3", "refill.wav"):
            res = sounds / name
            with resources.as_file(res) as p:
                if p.exists():
                    return Path(p)
    except (FileNotFoundError, ModuleNotFoundError, AttributeError):
        pass
    return None


class DesktopNotifier(Notifier):
    def __init__(
        self,
        sound: str | None = None,
        play_sound: bool = True,
        show_toast: bool = True,
    ) -> None:
        self.sound = sound
        self.play_sound = play_sound
        self.show_toast = show_toast

    def notify(self, event: RefillEvent) -> None:
        body = f"{event.provider} — your usage is back. Get back to work!"
        if self.play_sound:
            self._play()
        if self.show_toast:
            self._toast(body)

    # --- sound ---------------------------------------------------------------
    def _play(self) -> None:
        wav = Path(self.sound) if self.sound else _bundled_sound()
        try:
            if sys.platform.startswith("win"):
                self._play_windows(wav)
            elif sys.platform == "darwin":
                if wav:
                    subprocess.Popen(["afplay", str(wav)])
                else:
                    sys.stdout.write("\a")
                    sys.stdout.flush()
            else:
                self._play_linux(wav)
        except Exception:
            # A failed beep must never take down the watcher.
            try:
                sys.stdout.write("\a")
                sys.stdout.flush()
            except Exception:
                pass

    def _play_windows(self, wav: Path | None) -> None:
        import winsound

        if wav and wav.exists():
            if wav.suffix.lower() != ".wav":
                self._play_windows_media(wav)
                return
            winsound.PlaySound(
                str(wav), winsound.SND_FILENAME | winsound.SND_ASYNC
            )
        else:
            winsound.MessageBeep(winsound.MB_ICONASTERISK)

    def _play_linux(self, wav: Path | None) -> None:
        if wav and wav.exists():
            for player in ("paplay", "aplay", "ffplay", "mpg123", "mpv", "cvlc"):
                exe = shutil.which(player)
                if exe:
                    args = [exe, str(wav)]
                    if player == "ffplay":
                        args = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", str(wav)]
                    elif player in ("mpv", "cvlc"):
                        args = [exe, "--no-video", str(wav)]
                    subprocess.Popen(args)
                    return
        sys.stdout.write("\a")
        sys.stdout.flush()

    def _play_windows_media(self, sound: Path) -> None:
        from ctypes import windll  # Windows-only; import lazily so the module
        # imports cleanly on macOS/Linux (where ctypes.windll doesn't exist).

        alias = f"btw_{int(time.time() * 1000)}"
        mci = windll.winmm.mciSendStringW
        quoted = str(sound).replace('"', "")
        if mci(f'open "{quoted}" alias {alias}', None, 0, None) != 0:
            raise RuntimeError("cannot open media sound")
        try:
            if mci(f"play {alias}", None, 0, None) != 0:
                raise RuntimeError("cannot play media sound")
        except Exception:
            mci(f"close {alias}", None, 0, None)
            raise

    # --- toast ---------------------------------------------------------------
    def _toast(self, body: str) -> None:
        try:
            if sys.platform.startswith("win"):
                self._toast_windows(body)
            elif sys.platform == "darwin":
                self._toast_macos(body)
            else:
                self._toast_linux(body)
        except Exception:
            # Toast is a nicety; never let it crash the run.
            pass

    def _toast_windows(self, body: str) -> None:
        try:
            from winotify import Notification
        except ImportError:
            return  # sound already fired; skip the popup silently
        Notification(app_id=_TITLE, title=_TITLE, msg=body).show()

    def _toast_macos(self, body: str) -> None:
        exe = shutil.which("osascript")
        if exe:
            script = f'display notification "{body}" with title "{_TITLE}"'
            subprocess.Popen([exe, "-e", script])

    def _toast_linux(self, body: str) -> None:
        exe = shutil.which("notify-send")
        if exe:
            subprocess.Popen([exe, _TITLE, body])
