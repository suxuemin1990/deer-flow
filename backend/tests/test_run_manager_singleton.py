"""Tests for run_manager_singleton."""

from __future__ import annotations

import pytest


def setup_function():
    from deerflow.runtime.run_manager_singleton import reset_default_run_manager
    reset_default_run_manager()


def test_get_default_run_manager_raises_when_unset():
    from deerflow.runtime.run_manager_singleton import get_default_run_manager

    with pytest.raises(RuntimeError, match="No default run manager"):
        get_default_run_manager()


def test_set_then_get_returns_same_instance():
    from deerflow.runtime.run_manager_singleton import (
        get_default_run_manager,
        set_default_run_manager,
    )

    sentinel = object()
    set_default_run_manager(sentinel)  # type: ignore[arg-type]
    assert get_default_run_manager() is sentinel


def test_try_get_default_run_manager_returns_none_when_unset():
    from deerflow.runtime.run_manager_singleton import try_get_default_run_manager

    assert try_get_default_run_manager() is None


def test_try_get_default_run_manager_returns_instance_when_set():
    from deerflow.runtime.run_manager_singleton import (
        set_default_run_manager,
        try_get_default_run_manager,
    )

    sentinel = object()
    set_default_run_manager(sentinel)  # type: ignore[arg-type]
    assert try_get_default_run_manager() is sentinel
