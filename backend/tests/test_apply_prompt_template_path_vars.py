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
    """When per-thread paths are omitted, the rendered prompt keeps raw
    `{workspace_path}` / `{uploads_path}` / `{outputs_path}` placeholders so
    that ``SystemPromptPathMiddleware`` can substitute them at model-call
    time. ``skills_path`` is thread-independent, so it is pre-substituted to
    a sentinel string at construction time (no raw placeholder).
    """
    rendered = apply_prompt_template(
        subagent_enabled=False,
        max_concurrent_subagents=3,
        agent_name="DeerFlow",
        available_skills=set(),
    )
    # Per-thread placeholders are intentionally left raw for runtime substitution.
    assert "{workspace_path}" in rendered
    assert "{uploads_path}" in rendered
    assert "{outputs_path}" in rendered
    # skills_path is not per-thread; resolved at construction time.
    assert "{skills_path}" not in rendered
    # Old sentinel literals must be gone — they leaked to the LLM (regression S2).
    assert "<workspace not yet initialized>" not in rendered
    assert "<uploads not yet initialized>" not in rendered
    assert "<outputs not yet initialized>" not in rendered


def test_template_keeps_per_thread_placeholders_with_subagent_section():
    """When subagents are enabled and per-thread paths are None, the
    subagent_section (which embeds workspace_path inline in tool examples)
    must also keep raw `{workspace_path}` placeholders.
    """
    rendered = apply_prompt_template(
        subagent_enabled=True,
        max_concurrent_subagents=3,
        agent_name="DeerFlow",
        available_skills=set(),
        skills_path="/repo/skills",
    )
    assert "{workspace_path}" in rendered
    assert "<workspace not yet initialized>" not in rendered
