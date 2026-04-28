"""Tests for the store singleton."""

from __future__ import annotations


def test_get_returns_none_initially():
    from deerflow.runtime.store_singleton import (
        get_default_store,
        reset_default_store,
    )

    reset_default_store()
    assert get_default_store() is None


def test_set_and_get_roundtrip():
    from deerflow.runtime.store_singleton import (
        get_default_store,
        reset_default_store,
        set_default_store,
    )

    reset_default_store()
    sentinel = object()
    set_default_store(sentinel)
    try:
        assert get_default_store() is sentinel
    finally:
        reset_default_store()


def test_reset_clears_back_to_none():
    from deerflow.runtime.store_singleton import (
        get_default_store,
        reset_default_store,
        set_default_store,
    )

    set_default_store(object())
    reset_default_store()
    assert get_default_store() is None
