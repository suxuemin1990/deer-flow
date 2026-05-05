"""Subagent system_prompt template resolution.

Pulled out of ``deerflow.subagents.executor`` so tests can import the helper
without paying for the executor's heavy import chain (which is mocked in the
test conftest).
"""

from __future__ import annotations

import logging
from typing import Any

from deerflow.subagents.config import SubagentConfig

logger = logging.getLogger(__name__)


class _SafeFormatDict(dict):
    """Format-mapping that leaves unknown placeholders untouched.

    Lets us substitute path template variables (``{workspace_path}``,
    ``{uploads_path}``, ``{outputs_path}``, ``{skills_path}``) into a
    subagent's ``system_prompt`` without crashing on custom subagent
    prompts that contain literal braces or other unrelated placeholders.
    """

    def __missing__(self, key: str) -> str:  # type: ignore[override]
        return "{" + key + "}"


def _resolve_system_prompt(
    config: SubagentConfig,
    thread_data: Any | None,
    skills_path: str | None = None,
) -> str:
    """Substitute path template variables into a subagent's system_prompt.

    Always returns a string. Unknown ``{...}`` placeholders are preserved.
    """
    td: dict = dict(thread_data) if thread_data else {}
    values = {
        "workspace_path": td.get("workspace_path") or "<workspace not yet initialized>",
        "uploads_path": td.get("uploads_path") or "<uploads not yet initialized>",
        "outputs_path": td.get("outputs_path") or "<outputs not yet initialized>",
        "skills_path": skills_path or "<skills not configured>",
    }
    try:
        return config.system_prompt.format_map(_SafeFormatDict(values))
    except (KeyError, IndexError, ValueError) as exc:
        logger.warning(
            "Failed to format subagent system_prompt for %s (%s); using raw prompt",
            config.name,
            exc,
        )
        return config.system_prompt
