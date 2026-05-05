"""Verify the new get_sandbox() façade returns a singleton Sandbox."""

from deerflow.sandbox import Sandbox, get_sandbox


def test_get_sandbox_returns_singleton():
    s1 = get_sandbox()
    s2 = get_sandbox()
    assert s1 is s2
    assert isinstance(s1, Sandbox)
