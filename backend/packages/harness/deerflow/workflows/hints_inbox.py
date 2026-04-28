"""In-process hints inbox.

The original design tried to deliver hints by writing ``_hints`` into the
running workflow's checkpoint via ``aupdate_state``. That doesn't work: the
running ``Pregel`` keeps an in-memory copy of channel state and ignores
external updates, so the next node tick writes a sibling checkpoint that
overwrites the inject. Hints land on disk for one tick and then disappear.

Instead, we keep hints out of LangGraph state entirely. ``inject_hint`` pushes
into a process-local dict; workflow nodes drain it with ``pop_hints`` at the
start of each tick. No checkpoint forks possible.

Trade-offs:
- **Restart-fragile.** Hints in the inbox at gateway shutdown are lost. This
  matches the existing limitation that bg workflow tasks themselves don't
  survive gateway restarts (HANDOFF #5).
- **Single-process.** A multi-process gateway would need to swap this for a
  shared store (sqlite sidecar, redis, etc.). Single-process today, so the
  in-memory dict suffices.
- **Not in /state.** Pending hints are not visible via the thread state
  endpoint. ``get_workflow_progress`` exposes them via :func:`peek_hints`.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict

_inbox: dict[str, list[str]] = defaultdict(list)
_lock = asyncio.Lock()


async def push_hint(thread_id: str, hint: str) -> None:
    """Append *hint* to *thread_id*'s pending inbox."""
    async with _lock:
        _inbox[thread_id].append(hint)


async def pop_hints(thread_id: str) -> list[str]:
    """Atomically drain and return all pending hints for *thread_id*.

    Returns an empty list if no hints are pending. The thread's inbox is
    cleared in the same critical section, so concurrent ``pop_hints`` calls
    won't double-deliver a hint.
    """
    async with _lock:
        return _inbox.pop(thread_id, [])


async def peek_hints(thread_id: str) -> list[str]:
    """Return a snapshot of pending hints for *thread_id* without consuming.

    Returned list is independent — mutating it does not affect the inbox.
    """
    async with _lock:
        return list(_inbox.get(thread_id, []))


def reset_inbox() -> None:
    """Test-only helper: drop every queued hint across every thread."""
    _inbox.clear()
