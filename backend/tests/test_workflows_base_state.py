"""Unit tests for the workflow platform base state reducer."""

from deerflow.workflows.base_state import WorkflowBaseState, hints_reducer


def test_hints_reducer_appends_when_existing_present():
    assert hints_reducer(["a"], ["b"]) == ["a", "b"]


def test_hints_reducer_starts_from_empty_when_existing_none():
    assert hints_reducer(None, ["a"]) == ["a"]


def test_hints_reducer_returns_existing_when_new_none():
    assert hints_reducer(["a", "b"], None) == ["a", "b"]


def test_hints_reducer_explicit_empty_list_clears():
    assert hints_reducer(["a", "b"], []) == []


def test_hints_reducer_explicit_empty_list_clears_when_existing_none():
    assert hints_reducer(None, []) == []


def test_hints_reducer_both_none_returns_empty():
    assert hints_reducer(None, None) == []


def test_workflow_base_state_keys():
    keys = WorkflowBaseState.__optional_keys__
    assert "_parent_thread_id" in keys
    assert "_hints" in keys
    assert "_error" in keys
