"""hints_inbox.py was deleted in the 2026-04-29 redesign — guard against revival."""

import pytest


def test_hints_inbox_module_does_not_exist():
    with pytest.raises(ImportError):
        import deerflow.workflows.hints_inbox  # noqa: F401
