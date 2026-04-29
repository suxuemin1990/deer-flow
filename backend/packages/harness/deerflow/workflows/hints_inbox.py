"""Process-local async-safe inbox for runtime hint injection.

The Workflow Hub UI / inject_hint tool POSTs a hint; the POST handler
calls :func:`push`. The running workflow's loop node calls
:func:`pop_all` at each tick, drains pending hints, and emits them as
HumanMessages through its node return value. Because the running pregel
itself is the writer, its next checkpoint commit naturally includes the
new messages via the ``add_messages`` reducer — no race with sibling
checkpoints written via ``aupdate_state``.

Why not just write through ``messages`` channel directly:
    See bug 5 in the 2026-04-29 smoke doc. Briefly: the running task
    holds an in-memory channel view; sibling checkpoints written via
    ``aupdate_state`` are overwritten by the next step's commit.

Why process-local (no persistence):
    A hint pending at gateway restart was always going to be lost
    anyway — the running workflow task itself dies with the process.
    Keeping the inbox in-memory avoids a second source of truth and
    sidesteps SQLite write contention.
"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass

# Module-level state. Reset only via reset_for_test().
_INBOX: dict[str, list[InboxHint]] = {}
_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class InboxHint:
    """A pending hint waiting to be drained by a running workflow.

    Attributes:
        id: Stable unique id. The workflow node MUST use this as the
            HumanMessage id when constructing the message, so frontend
            optimistic bubbles can dedupe against polled state.
        content: User-supplied hint text.
    """

    id: str
    content: str


async def push(child_thread_id: str, content: str) -> str:
    """Append a hint to the inbox; return its stable id."""
    hint = InboxHint(id=str(uuid.uuid4()), content=content)
    async with _LOCK:
        _INBOX.setdefault(child_thread_id, []).append(hint)
    return hint.id


async def pop_all(child_thread_id: str) -> list[InboxHint]:
    """Atomically drain all pending hints for a thread.

    Returns an empty list if the thread has no pending hints.
    """
    async with _LOCK:
        return _INBOX.pop(child_thread_id, [])


def reset_for_test() -> None:
    """Wipe inbox state. Test-only."""
    _INBOX.clear()


__all__ = ["InboxHint", "push", "pop_all"]
