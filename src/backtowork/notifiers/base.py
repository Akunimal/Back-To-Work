"""Notifier interface. Built-ins: terminal (banner) and desktop (sound + toast)."""

from __future__ import annotations

import abc

from ..models import RefillEvent


class Notifier(abc.ABC):
    @abc.abstractmethod
    def notify(self, event: RefillEvent) -> None: ...
