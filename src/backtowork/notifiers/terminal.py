"""Terminal notifier: rings the bell + prints the ASCII celebration banner."""

from __future__ import annotations

from rich.align import Align
from rich.console import Console
from rich.text import Text

from ..art import CELEBRATION
from ..models import RefillEvent
from .base import Notifier


class TerminalNotifier(Notifier):
    def __init__(self, console: Console) -> None:
        self.console = console

    def notify(self, event: RefillEvent) -> None:
        self.console.bell()  # audible terminal bell
        banner = Text(CELEBRATION, style="bold green")
        self.console.print()
        self.console.print(Align.center(banner))
        when = event.at.astimezone().strftime("%H:%M:%S")
        self.console.print(
            Align.center(
                Text(f"  {event.provider}  ·  {when}  ", style="green")
            )
        )
        self.console.print()
