"""Tests for the in-process hints inbox."""

from __future__ import annotations

import pytest


def setup_function():
    from deerflow.workflows.hints_inbox import reset_inbox

    reset_inbox()


@pytest.mark.asyncio
async def test_push_then_pop_returns_hints_in_order():
    from deerflow.workflows.hints_inbox import pop_hints, push_hint

    await push_hint("t1", "first")
    await push_hint("t1", "second")
    assert await pop_hints("t1") == ["first", "second"]


@pytest.mark.asyncio
async def test_pop_drains_inbox():
    from deerflow.workflows.hints_inbox import pop_hints, push_hint

    await push_hint("t1", "h")
    assert await pop_hints("t1") == ["h"]
    assert await pop_hints("t1") == []


@pytest.mark.asyncio
async def test_pop_unknown_thread_returns_empty_list():
    from deerflow.workflows.hints_inbox import pop_hints

    assert await pop_hints("nope") == []


@pytest.mark.asyncio
async def test_peek_does_not_consume():
    from deerflow.workflows.hints_inbox import peek_hints, pop_hints, push_hint

    await push_hint("t1", "a")
    await push_hint("t1", "b")
    assert await peek_hints("t1") == ["a", "b"]
    # Still there.
    assert await peek_hints("t1") == ["a", "b"]
    # And pop still drains both.
    assert await pop_hints("t1") == ["a", "b"]


@pytest.mark.asyncio
async def test_peek_returns_independent_list():
    """Mutating the returned list must not affect the inbox."""
    from deerflow.workflows.hints_inbox import peek_hints, pop_hints, push_hint

    await push_hint("t1", "a")
    snap = await peek_hints("t1")
    snap.append("hacked")
    assert await pop_hints("t1") == ["a"]


@pytest.mark.asyncio
async def test_threads_are_isolated():
    from deerflow.workflows.hints_inbox import pop_hints, push_hint

    await push_hint("t1", "for-t1")
    await push_hint("t2", "for-t2")
    assert await pop_hints("t1") == ["for-t1"]
    assert await pop_hints("t2") == ["for-t2"]


@pytest.mark.asyncio
async def test_reset_clears_all():
    from deerflow.workflows.hints_inbox import pop_hints, push_hint, reset_inbox

    await push_hint("t1", "a")
    await push_hint("t2", "b")
    reset_inbox()
    assert await pop_hints("t1") == []
    assert await pop_hints("t2") == []
