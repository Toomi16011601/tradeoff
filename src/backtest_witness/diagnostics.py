"""Explicit local-only exception traces, separate from portable evidence.

The chosen file may contain exception messages, source lines and private paths.
Nothing is recorded unless the caller enters ``local_diagnostics(path)``.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import traceback


class DiagnosticsError(ValueError):
    """The explicitly requested private diagnostics file could not be saved."""


class _Recorder:
    def __init__(self):
        self.exceptions = []
        self.traces = []

    def record(self, exc):
        if any(previous is exc for previous in self.exceptions):
            return
        self.exceptions.append(exc)
        trace = traceback.TracebackException.from_exception(exc, capture_locals=False)
        self.traces.append(''.join(trace.format(chain=True)))


_active_recorder = ContextVar('backtest_witness_local_diagnostics', default=None)
_HEADER = (
    'BacktestWitness PRIVATE LOCAL DIAGNOSTICS\n'
    'May contain private exception messages, source lines and paths.\n'
    'Keep this file local; review it before sharing. No local variables are captured.\n\n'
)


def record_exception(exc):
    """Record a caught exception and its chain only within an opted-in context."""
    recorder = _active_recorder.get()
    if recorder is not None:
        recorder.record(exc)


def _finish(fd, destination, recorder):
    payload = (_HEADER + ('\n\n'.join(recorder.traces) if recorder.traces
                         else 'No exceptions recorded.\n')).encode('utf-8', errors='backslashreplace')
    try:
        remaining = memoryview(payload)
        while remaining:
            written = os.write(fd, remaining)
            if written <= 0:
                raise OSError('Diagnostics write made no progress')
            remaining = remaining[written:]
        os.fsync(fd)
        os.close(fd)
    except OSError:
        try:
            os.ftruncate(fd, 0)
        except OSError:
            pass
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            destination.unlink()
        except OSError:
            pass
        raise DiagnosticsError('Private diagnostics could not be saved; no report includes the raw exception') from None


@contextmanager
def local_diagnostics(path):
    """Collect private tracebacks in one new owner-readable local file.

    Creation is exclusive: existing files and final-component symlinks are
    refused before the body runs. The parent directory must already exist.
    Callers must keep this destination outside their portable report folder.
    Exceptions escaping the body are recorded and continue to propagate.
    """
    destination = Path(path).expanduser()
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    try:
        fd = os.open(destination, flags, 0o600)
    except OSError:
        raise DiagnosticsError('Private diagnostics requires a new writable file; existing files and symlinks are refused') from None
    recorder = _Recorder()
    token = _active_recorder.set(recorder)
    try:
        try:
            yield
        except BaseException as exc:
            record_exception(exc)
            raise
    finally:
        _active_recorder.reset(token)
        _finish(fd, destination, recorder)
