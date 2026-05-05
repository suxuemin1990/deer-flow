"""Verify ThreadState no longer carries a sandbox field."""
from deerflow.agents.thread_state import ThreadState


def test_thread_state_no_sandbox_field():
    annotations = ThreadState.__annotations__
    assert "sandbox" not in annotations
    # thread_data stays
    assert "thread_data" in annotations
