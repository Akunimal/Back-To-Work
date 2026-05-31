"""Command-line interface.

  backtowork watch     live monitor with a big green countdown (default)
  backtowork status    poll every provider once and print a table
  backtowork test      fire a fake refill so you can see the banner + hear the sound

Quick start with no config file:
  backtowork watch --reset 3h     # count down 3 hours, then sound + toast
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from datetime import datetime, timezone

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from . import __version__
from .art import LOGO, battery, big_clock, bubbles_frame
from .config import find_config, load_providers
from .core import Monitor
from .models import QuotaState, RefillEvent, Status
from .notifiers.desktop import DesktopNotifier
from .notifiers.terminal import TerminalNotifier
from .providers.base import build

_STATUS_STYLE = {
    Status.AVAILABLE: ("● available", "bold green"),
    Status.EXHAUSTED: ("○ exhausted", "bold red"),
    Status.UNKNOWN: ("? unknown", "yellow"),
}


def _countdown_label(reset_at: datetime | None) -> str:
    if reset_at is None:
        return "—"
    secs = int((reset_at - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        return "due"
    h, rem = divmod(secs, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m" if h else f"{m}m{s:02d}s"


def _soonest_reset(states: dict[str, QuotaState]) -> datetime | None:
    resets = [
        s.reset_at
        for s in states.values()
        if s.status == Status.EXHAUSTED and s.reset_at is not None
    ]
    return min(resets) if resets else None


def _status_table(states: dict[str, QuotaState]) -> Table:
    table = Table(expand=True, box=None, pad_edge=False)
    table.add_column("coder", style="bold cyan", no_wrap=True)
    table.add_column("status")
    table.add_column("credit", justify="left")
    table.add_column("resets in", justify="right")
    table.add_column("note", style="dim", overflow="fold")
    for name, st in states.items():
        label, style = _STATUS_STYLE[st.status]
        table.add_row(
            name,
            Text(label, style=style),
            battery(st.pct_used),
            _countdown_label(st.reset_at),
            st.detail or "",
        )
    return table


def _dashboard(states: dict[str, QuotaState], t: float) -> Panel:
    reset_at = _soonest_reset(states)
    any_exhausted = any(s.status == Status.EXHAUSTED for s in states.values())

    if reset_at is not None:
        secs = int((reset_at - datetime.now(timezone.utc)).total_seconds())
        hero: Text = Text(big_clock(secs), style="bold green")
    elif any_exhausted:
        hero = Text(bubbles_frame(t), style="green")
    else:
        hero = Text("BACK TO WORK", style="bold green")

    body = Group(
        Text(""),
        Align.center(hero),
        Text(""),
        _status_table(states),
    )
    stamp = datetime.now().strftime("%H:%M:%S")
    return Panel(
        body,
        title=Text(LOGO, style="bold magenta"),
        subtitle=f"last poll {stamp} · Ctrl-C to quit",
        border_style="green" if not any_exhausted else "magenta",
    )


def _build_notifiers(args, settings, console) -> list:
    notifiers = [TerminalNotifier(console)]
    play_sound = settings.get("play_sound", True) and not getattr(args, "no_sound", False)
    show_toast = settings.get("show_toast", True) and not getattr(args, "no_toast", False)
    sound = getattr(args, "sound", None) or settings.get("sound")
    notifiers.append(
        DesktopNotifier(sound=sound, play_sound=play_sound, show_toast=show_toast)
    )
    return notifiers


def _load_providers(args, console):
    """Return (providers, settings) or (None, {}). Honors --reset as a zero-config
    shortcut that synthesizes a manual provider."""
    reset = getattr(args, "reset", None)
    path = find_config(args.config)

    if path is None:
        if reset:
            try:
                provider = build("manual", "claude", {"reset_at": reset})
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]bad --reset value:[/red] {exc}")
                return None, {}
            return [provider], {}
        console.print(
            "[red]no config found.[/red] create backtowork.toml "
            "(see config.example.toml), pass --config, or use --reset <when>."
        )
        return None, {}

    try:
        providers, settings = load_providers(path)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]config error in {path}:[/red] {exc}")
        return None, {}

    if reset:  # --reset overrides config with a precise manual countdown
        try:
            providers = [build("manual", "claude", {"reset_at": reset})]
        except Exception as exc:  # noqa: BLE001
            console.print(f"[red]bad --reset value:[/red] {exc}")
            return None, {}
    return providers, settings


def cmd_watch(args: argparse.Namespace, console: Console) -> int:
    providers, settings = _load_providers(args, console)
    if providers is None:
        return 1

    monitor = Monitor(
        providers,
        idle_interval=float(settings.get("idle_interval", 60)),
        fast_interval=float(settings.get("fast_interval", 10)),
    )
    notifiers = _build_notifiers(args, settings, console)

    shared: dict[str, QuotaState] = monitor.poll_once()
    lock = threading.Lock()

    def on_tick(states: dict[str, QuotaState]) -> None:
        nonlocal shared
        with lock:
            shared = states

    def on_refill(event: RefillEvent) -> None:
        for n in notifiers:
            try:
                n.notify(event)
            except Exception:  # noqa: BLE001
                pass

    worker = threading.Thread(
        target=monitor.run, args=(on_tick, on_refill), daemon=True
    )
    worker.start()

    start = time.monotonic()
    try:
        with Live(console=console, screen=False, refresh_per_second=4) as live:
            while worker.is_alive():
                with lock:
                    states = dict(shared)
                live.update(_dashboard(states, time.monotonic() - start))
                time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    finally:
        monitor.stop()
    console.print("[dim]stopped.[/dim]")
    return 0


def cmd_status(args: argparse.Namespace, console: Console) -> int:
    providers, _ = _load_providers(args, console)
    if providers is None:
        return 1
    monitor = Monitor(providers)
    console.print(_dashboard(monitor.poll_once(), 0.0))
    return 0


def cmd_test(args: argparse.Namespace, console: Console) -> int:
    event = RefillEvent(
        provider="demo", at=datetime.now(timezone.utc), previous=Status.EXHAUSTED
    )
    for n in _build_notifiers(args, {}, console):
        try:
            n.notify(event)
        except Exception as exc:  # noqa: BLE001
            console.print(f"[yellow]notifier failed:[/yellow] {exc}")
    return 0


def _add_watch_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--reset", metavar="WHEN",
                   help="count down to this time: '3h', '90m', '2h30m', or an ISO timestamp")
    p.add_argument("--sound", metavar="PATH", help="custom .wav to play on refill")
    p.add_argument("--no-sound", action="store_true", help="don't play a sound")
    p.add_argument("--no-toast", action="store_true", help="don't show a desktop toast")


def _force_utf8() -> None:
    """Windows legacy consoles default to cp1252, which can't encode the box-art
    and emoji glyphs we print (raises UnicodeEncodeError). Switch the standard
    streams to UTF-8 and flip the console output code page to UTF-8 (65001) so
    the banner and big countdown render."""
    for stream in (sys.stdout, sys.stderr):
        reconfig = getattr(stream, "reconfigure", None)
        if reconfig is not None:
            try:
                reconfig(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except Exception:
            pass


def _make_console() -> Console:
    """On Windows, bypass the win32 console API (which encodes via the active code
    page and chokes on our Unicode art). We pass rich an explicit UTF-8 TextIOWrapper
    so it never touches the legacy renderer, regardless of terminal type or whether
    the binary is frozen by PyInstaller."""
    if sys.platform.startswith("win"):
        import io

        try:
            buf = getattr(sys.stdout, "buffer", None)
            if buf is not None:
                safe = io.TextIOWrapper(
                    buf, encoding="utf-8", errors="replace", line_buffering=True
                )
                return Console(file=safe, legacy_windows=False)
        except Exception:
            pass
        return Console(legacy_windows=False)
    return Console()


def main(argv: list[str] | None = None) -> int:
    _force_utf8()
    parser = argparse.ArgumentParser(
        prog="backtowork",
        description="Tells you (with a sound) when your coder's credit comes back.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", help="path to config TOML")
    sub = parser.add_subparsers(dest="cmd")

    p_watch = sub.add_parser("watch", help="live monitor with a big countdown (default)")
    _add_watch_flags(p_watch)
    p_status = sub.add_parser("status", help="poll once and print")
    _add_watch_flags(p_status)
    p_test = sub.add_parser("test", help="show the banner + play the sound")
    _add_watch_flags(p_test)

    args = parser.parse_args(argv)
    console = _make_console()
    cmd = args.cmd or "watch"
    if cmd == "watch" and args.cmd is None:
        # default subcommand: fill in watch's flag defaults
        args.reset = getattr(args, "reset", None)
        args.sound = getattr(args, "sound", None)
        args.no_sound = getattr(args, "no_sound", False)
        args.no_toast = getattr(args, "no_toast", False)
    return {"watch": cmd_watch, "status": cmd_status, "test": cmd_test}[cmd](
        args, console
    )


if __name__ == "__main__":
    sys.exit(main())
