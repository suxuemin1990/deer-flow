# backend/tests/test_hints_inbox.py
"""Unit tests for workflows.hints_inbox.

The inbox is a process-local async-safe queue keyed by workflow child
thread id. POST handlers push hints; running workflow nodes drain them.
"""
from __future__ import annotations

import asyncio

import pytest


@pytest.mark.asyncio
async def test_push_then_pop_all_returns_in_order():
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    await ib.push("tid-1", "first")
    await ib.push("tid-1", "second")
    drained = await ib.pop_all("tid-1")
    assert [h.content for h in drained] == ["first", "second"]


@pytest.mark.asyncio
async def test_pop_all_when_empty_returns_empty_list():
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    drained = await ib.pop_all("tid-empty")
    assert drained == []


@pytest.mark.asyncio
async def test_pop_all_is_atomic_drain():
    """After pop_all, the queue is empty for that thread."""
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    await ib.push("tid-2", "a")
    await ib.pop_all("tid-2")
    assert await ib.pop_all("tid-2") == []


@pytest.mark.asyncio
async def test_per_thread_isolation():
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    await ib.push("tid-A", "for A")
    await ib.push("tid-B", "for B")
    drained_a = await ib.pop_all("tid-A")
    drained_b = await ib.pop_all("tid-B")
    assert [h.content for h in drained_a] == ["for A"]
    assert [h.content for h in drained_b] == ["for B"]


@pytest.mark.asyncio
async def test_pushed_hints_carry_stable_ids():
    """Each push generates a stable id, returned in the InboxHint dataclass.

    Workflow nodes use this id when constructing HumanMessage so the
    frontend can dedupe optimistic UI bubbles against polled state.
    """
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()
    h_id = await ib.push("tid-3", "hello")
    drained = await ib.pop_all("tid-3")
    assert len(drained) == 1
    assert drained[0].id == h_id
    assert drained[0].content == "hello"


@pytest.mark.asyncio
async def test_concurrent_push_and_pop_no_loss():
    """Async-safe under interleaved push and pop_all.

    Real scenario: POST handlers push hints while the workflow loop
    node concurrently drains via pop_all. The inbox must guarantee
    no hint is lost and no hint is duplicated under arbitrary
    interleaving.
    """
    from deerflow.workflows import hints_inbox as ib

    ib.reset_for_test()

    pushed: list[str] = [f"msg-{i}" for i in range(50)]
    drained_all: list = []
    drain_lock = asyncio.Lock()

    async def pusher(content: str) -> None:
        await ib.push("tid-c", content)

    async def popper() -> None:
        # Yield first so at least some pushes have a chance to run.
        await asyncio.sleep(0)
        got = await ib.pop_all("tid-c")
        async with drain_lock:
            drained_all.extend(got)

    tasks = [pusher(c) for c in pushed]
    tasks.extend(popper() for _ in range(10))
    await asyncio.gather(*tasks)

    # Final drain to capture anything still pending after the gather.
    drained_all.extend(await ib.pop_all("tid-c"))

    contents = sorted(h.content for h in drained_all)
    ids = [h.id for h in drained_all]
    assert contents == sorted(pushed), f"missing/extra messages: {contents!r}"
    assert len(ids) == len(set(ids)), f"duplicate ids: {ids!r}"
