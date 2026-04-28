"""Tests for checkpointer singleton."""

import pytest


def test_get_raises_when_unset():
    from deerflow.runtime.checkpointer_singleton import (
        get_default_checkpointer,
        reset_default_checkpointer,
    )

    reset_default_checkpointer()
    with pytest.raises(RuntimeError, match="No default checkpointer"):
        get_default_checkpointer()


def test_set_and_get_roundtrip():
    from langgraph.checkpoint.memory import InMemorySaver

    from deerflow.runtime.checkpointer_singleton import (
        get_default_checkpointer,
        reset_default_checkpointer,
        set_default_checkpointer,
    )

    reset_default_checkpointer()
    saver = InMemorySaver()
    set_default_checkpointer(saver)
    assert get_default_checkpointer() is saver
    reset_default_checkpointer()
