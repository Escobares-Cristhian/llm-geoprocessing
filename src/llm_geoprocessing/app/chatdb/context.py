# Context vars for log correlation.
from __future__ import annotations

from contextvars import ContextVar
from typing import Optional

_session_id: ContextVar[Optional[str]] = ContextVar("chatdb_session_id", default=None)
_run_id: ContextVar[Optional[str]] = ContextVar("chatdb_run_id", default=None)


def set_session_id(session_id: Optional[str]) -> None:
    _session_id.set(str(session_id) if session_id is not None else None)


def get_session_id() -> Optional[str]:
    return _session_id.get()


def set_run_id(run_id: Optional[str]) -> None:
    _run_id.set(str(run_id) if run_id is not None else None)


def get_run_id() -> Optional[str]:
    return _run_id.get()
