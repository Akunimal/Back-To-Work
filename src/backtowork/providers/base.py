"""Provider interface and registry.

A provider knows ONE thing: how to read the current quota state of one coder.
It knows nothing about polling, the UI, or notifications.
"""

from __future__ import annotations

import abc
from typing import Callable

from ..models import QuotaState

_REGISTRY: dict[str, type["Provider"]] = {}


def register(kind: str) -> Callable[[type["Provider"]], type["Provider"]]:
    def deco(cls: type["Provider"]) -> type["Provider"]:
        _REGISTRY[kind] = cls
        return cls

    return deco


def build(kind: str, name: str, options: dict) -> "Provider":
    if kind not in _REGISTRY:
        raise ValueError(
            f"unknown provider kind '{kind}'. known: {sorted(_REGISTRY)}"
        )
    return _REGISTRY[kind](name=name, options=options)


class Provider(abc.ABC):
    def __init__(self, name: str, options: dict) -> None:
        self.name = name
        self.options = options

    @abc.abstractmethod
    def read_state(self) -> QuotaState:
        """Return the current quota state. Must not raise; on error return
        a QuotaState with Status.UNKNOWN and a `detail` explaining why."""
        raise NotImplementedError
