"""The engine's console text, captured (KI-05, re/27; non-frozen).

GSAS-II prints what it does not return: ``DoPeakFit``'s "Refinement failed - singular matrix" and
"Removing parameter: ..." lines, ``Refine``'s SVD notes, the constraint-generation notices -- all through
Python's ``print`` (``GSASIIfiles.G2Print``). PowderLine carries the structured parts elsewhere (EB-32
messages, convergence, undetermined ESDs, ``requested_not_varied`` dispositions); what remains is kept here,
as text, for the one reader who needs it: someone debugging a failed run.

:func:`capture_console` replaces ``sys.stdout`` for the duration of the engine run with a stream that writes
to both the real stdout (the verbose progress prints keep going where they went) and a bounded buffer that
keeps the **tail** of the text. :func:`attach_console` puts that tail into a failed envelope's ``failure``
record as ``console_tail`` (and, for a verbose run that succeeded, under ``engine_details``). The replacement
is process-global: in-process runs are single-threaded, and the GSAS-II server runs one job at a time
(re/14). Output written by compiled code straight to file descriptor 1 is not captured and not claimed.
"""
from __future__ import annotations

import contextlib
import io
import sys
from typing import Iterator, Optional

#: How much of the console's tail is kept (characters).
MAX_CONSOLE_CHARS = 64 * 1024


class ConsoleTail:
    """A bounded text buffer that keeps the last :data:`MAX_CONSOLE_CHARS` characters written."""

    def __init__(self, limit: int = MAX_CONSOLE_CHARS):
        self.limit = int(limit)
        self._parts: list[str] = []
        self._size = 0
        self.truncated = False

    def write(self, s: str) -> None:
        if not s:
            return
        self._parts.append(s)
        self._size += len(s)
        while self._size > self.limit and self._parts:
            head = self._parts[0]
            excess = self._size - self.limit
            if len(head) <= excess:
                self._parts.pop(0)
                self._size -= len(head)
            else:
                self._parts[0] = head[excess:]
                self._size -= excess
            self.truncated = True

    def text(self) -> str:
        return "".join(self._parts)


class _Tee(io.TextIOBase):
    """``sys.stdout`` stand-in: everything goes to the real stream and to the tail buffer."""

    def __init__(self, real, tail: ConsoleTail):
        self._real = real
        self._tail = tail

    def write(self, s) -> int:  # type: ignore[override]
        s = str(s)
        if self._real is not None:                       # pythonw / an embedding host: no stdout at all
            try:
                self._real.write(s)
            except (ValueError, OSError):  # a closed or unwritable real stdout must not kill the run
                pass
        self._tail.write(s)
        return len(s)

    def flush(self) -> None:
        if self._real is None:
            return
        try:
            self._real.flush()
        except (ValueError, OSError):
            pass

    def writable(self) -> bool:
        return True

    @property
    def encoding(self):  # type: ignore[override]
        return getattr(self._real, "encoding", None) or "utf-8"

    def isatty(self) -> bool:
        try:
            return bool(self._real is not None and self._real.isatty())
        except (ValueError, OSError):
            return False

    def fileno(self) -> int:
        if self._real is None:
            raise OSError("no real stdout to report a file descriptor for")
        return self._real.fileno()


@contextlib.contextmanager
def capture_console(limit: int = MAX_CONSOLE_CHARS) -> Iterator[ConsoleTail]:
    """Tee ``sys.stdout`` into a :class:`ConsoleTail` for the block's duration."""
    tail = ConsoleTail(limit)
    with contextlib.redirect_stdout(_Tee(sys.stdout, tail)):
        yield tail


def attach_console(envelope: dict, tail: Optional[ConsoleTail], *, verbose: bool = False) -> dict:
    """Put the captured tail on the envelope: ``failure.console_tail`` for a failed run (``None`` when the
    engine printed nothing), ``engine_details.console_tail`` for a verbose run that succeeded. Returns the
    envelope."""
    if tail is None:
        return envelope
    text = tail.text()
    if tail.truncated and text:
        text = "[... earlier console text dropped ...]\n" + text
    if envelope.get("status") == "failed" and isinstance(envelope.get("failure"), dict):
        envelope["failure"]["console_tail"] = text or None
    elif verbose and text:
        details = envelope.setdefault("engine_details", None)
        if isinstance(details, dict):
            details["console_tail"] = text
        else:
            envelope["engine_details"] = {"console_tail": text}
    return envelope
