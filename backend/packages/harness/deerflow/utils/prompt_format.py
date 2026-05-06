"""Shared `str.format_map`-compatible dict that preserves unknown placeholders."""

from __future__ import annotations


class SafeFormatDict(dict):
    """`dict` whose `__missing__` returns ``{key}`` so `str.format_map` leaves
    unknown placeholders untouched.

    Used by:
    - `deerflow.subagents.prompt_resolver` to substitute path template
      variables into subagent prompts at dispatch time.
    - `deerflow.agents.lead_agent.prompt.apply_prompt_template` to keep
      `{workspace_path}`/`{uploads_path}`/`{outputs_path}` placeholders in
      the lead-agent system prompt when per-thread paths aren't yet known.
    - `deerflow.agents.middlewares.system_prompt_path_middleware` to
      substitute those leftover placeholders at model-call time.
    """

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return "{" + key + "}"
