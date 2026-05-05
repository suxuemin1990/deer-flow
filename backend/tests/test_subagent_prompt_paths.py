"""Verify subagent prompts substitute path variables."""
from deerflow.subagents.builtins.bash_agent import build_system_prompt as build_bash
from deerflow.subagents.builtins.general_purpose import build_system_prompt as build_general


def test_general_purpose_substitutes_paths():
    rendered = build_general(
        workspace_path="/ws",
        uploads_path="/up",
        outputs_path="/out",
        skills_path="/sk",
    )
    assert "/mnt/user-data" not in rendered
    assert "/ws" in rendered
    assert "/up" in rendered
    assert "/out" in rendered


def test_bash_agent_substitutes_paths():
    rendered = build_bash(
        workspace_path="/ws",
        uploads_path="/up",
        outputs_path="/out",
        skills_path="/sk",
    )
    assert "/mnt/user-data" not in rendered
    assert "/ws" in rendered
    assert "/up" in rendered
    assert "/out" in rendered


def test_default_paths_when_none_provided():
    """Builders work without per-thread paths (placeholder fallbacks)."""
    for build in (build_general, build_bash):
        rendered = build()
        assert "{workspace_path}" not in rendered
        assert "{uploads_path}" not in rendered


def test_executor_threads_paths_into_prompt():
    """SubagentExecutor formats the system_prompt with thread_data paths at dispatch time."""
    from deerflow.subagents.builtins.general_purpose import GENERAL_PURPOSE_CONFIG
    from deerflow.subagents.prompt_resolver import _resolve_system_prompt

    rendered = _resolve_system_prompt(
        GENERAL_PURPOSE_CONFIG,
        thread_data={
            "workspace_path": "/real/workspace",
            "uploads_path": "/real/uploads",
            "outputs_path": "/real/outputs",
        },
    )
    assert "/real/workspace" in rendered
    assert "/real/uploads" in rendered
    assert "/real/outputs" in rendered
    assert "/mnt/user-data" not in rendered


def test_executor_falls_back_when_no_thread_data():
    from deerflow.subagents.builtins.bash_agent import BASH_AGENT_CONFIG
    from deerflow.subagents.prompt_resolver import _resolve_system_prompt

    rendered = _resolve_system_prompt(BASH_AGENT_CONFIG, thread_data=None)
    # No crash; placeholder fallbacks present
    assert "{workspace_path}" not in rendered
    assert "/mnt/user-data" not in rendered
