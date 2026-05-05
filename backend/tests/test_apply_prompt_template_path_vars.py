"""Verify apply_prompt_template substitutes path variables for /mnt literals."""
from deerflow.agents.lead_agent.prompt import apply_prompt_template, warm_enabled_skills_cache


def test_template_substitutes_path_vars():
    warm_enabled_skills_cache()
    rendered = apply_prompt_template(
        subagent_enabled=True,
        max_concurrent_subagents=3,
        agent_name="DeerFlow",
        available_skills=None,
        workspace_path="/var/lib/deerflow/threads/abc/user-data/workspace",
        uploads_path="/var/lib/deerflow/threads/abc/user-data/uploads",
        outputs_path="/var/lib/deerflow/threads/abc/user-data/outputs",
        skills_path="/repo/skills",
    )
    assert "/var/lib/deerflow/threads/abc/user-data/workspace" in rendered
    assert "/var/lib/deerflow/threads/abc/user-data/uploads" in rendered
    assert "/var/lib/deerflow/threads/abc/user-data/outputs" in rendered
    assert "/repo/skills" in rendered
    assert "/mnt/user-data" not in rendered
    # Note: /mnt/acp-workspace IS allowed to remain (it's an ACP container path,
    # not a deerflow virtual path). /mnt/skills must be gone.
    assert "/mnt/skills" not in rendered


def test_template_default_paths_when_none_provided():
    """When the four kwargs are omitted, prompt still renders with placeholder fallback."""
    rendered = apply_prompt_template(
        subagent_enabled=False,
        max_concurrent_subagents=3,
        agent_name="DeerFlow",
        available_skills=set(),
    )
    # Must not crash; must not contain raw {workspace_path} placeholder
    assert "{workspace_path}" not in rendered
    assert "{skills_path}" not in rendered
