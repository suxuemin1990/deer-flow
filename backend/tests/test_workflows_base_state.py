"""Unit tests for the workflow platform base state."""

from deerflow.workflows.base_state import WorkflowBaseState


def test_workflow_base_state_keys():
    keys = WorkflowBaseState.__optional_keys__
    assert "_parent_thread_id" in keys
    assert "_error" in keys
    # Hints are no longer a state channel — they live in hints_inbox.
    assert "_hints" not in keys
