"""Generic, coder-agnostic provider.

You give it a shell command. The exit code tells Back To Work the state:

    exit 0   -> AVAILABLE   (there is credit)
    exit 75  -> EXHAUSTED   (EX_TEMPFAIL: out of credit / rate-limited)
    anything else -> UNKNOWN

Optionally, the command may print a line like:

    reset_at=2026-05-30T18:00:00Z

on stdout to tell Back To Work when the quota is expected to refill. This lets
the adaptive poller sleep until just before the reset instead of busy-polling.

This is the provider that works with ANY coder: wrap whatever check you already
do (a cheap probe call, parsing a log, hitting a status endpoint) in a tiny
script that follows the exit-code convention.
"""

from __future__ import annotations

import shlex
import subprocess
from datetime import datetime

from ..models import QuotaState, Status
from .base import Provider, register

EX_TEMPFAIL = 75


def _parse_reset(stdout: str) -> datetime | None:
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("reset_at="):
            raw = line.split("=", 1)[1].strip()
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except ValueError:
                return None
    return None


@register("command")
class CommandProvider(Provider):
    def read_state(self) -> QuotaState:
        cmd = self.options.get("command")
        if not cmd:
            return QuotaState(Status.UNKNOWN, detail="no 'command' configured")

        timeout = float(self.options.get("timeout", 20))
        args = cmd if isinstance(cmd, list) else shlex.split(cmd)

        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return QuotaState(Status.UNKNOWN, detail=f"command timed out ({timeout}s)")
        except OSError as exc:
            return QuotaState(Status.UNKNOWN, detail=f"command failed: {exc}")

        reset_at = _parse_reset(proc.stdout)

        if proc.returncode == 0:
            return QuotaState(Status.AVAILABLE, reset_at=reset_at)
        if proc.returncode == EX_TEMPFAIL:
            return QuotaState(Status.EXHAUSTED, reset_at=reset_at, detail="rate-limited")
        return QuotaState(
            Status.UNKNOWN,
            detail=f"exit {proc.returncode}: {proc.stderr.strip()[:120]}",
        )
