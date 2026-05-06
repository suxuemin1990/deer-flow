"""Substitute per-thread path placeholders in the system message at model-call time.

`apply_prompt_template` runs at agent construction time and doesn't yet know
the active thread's workspace/uploads/outputs paths. It emits raw
`{workspace_path}` / `{uploads_path}` / `{outputs_path}` placeholders into
the rendered prompt; this middleware substitutes them just before each
model call using `state["thread_data"]`.

Symmetric with `deerflow.subagents.prompt_resolver._resolve_system_prompt`,
which solves the same problem on the subagent dispatch path.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import override

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain.agents.middleware.types import ModelCallResult, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from deerflow.utils.prompt_format import SafeFormatDict

logger = logging.getLogger(__name__)

_PLACEHOLDER_KEYS = ("workspace_path", "uploads_path", "outputs_path")


def _has_placeholder(text: str) -> bool:
    return any(f"{{{key}}}" in text for key in _PLACEHOLDER_KEYS)


class SystemPromptPathMiddleware(AgentMiddleware[AgentState]):
    """Replace `{workspace_path}` / `{uploads_path}` / `{outputs_path}` in
    the request's system message using `state["thread_data"]`.

    Idempotent: skips when no placeholder is present (after substitution
    or for prompts that never carried them).
    """

    def _resolved_system_message(self, request: ModelRequest) -> SystemMessage | None:
        sm = request.system_message
        if sm is None:
            return None
        # Only string content is supported by the placeholder substitution;
        # SystemMessage with structured content (rare) is left untouched.
        if not isinstance(sm.content, str):
            return None
        if not _has_placeholder(sm.content):
            return None

        thread_data = (request.state or {}).get("thread_data") or {}
        values: dict[str, str] = {}
        for key in _PLACEHOLDER_KEYS:
            value = thread_data.get(key)
            if value:
                values[key] = value
        if not values:
            # No thread paths available — leave placeholders as-is. The
            # middleware can fire again on a later turn once
            # ThreadDataMiddleware has populated `thread_data`.
            return None

        try:
            substituted = sm.content.format_map(SafeFormatDict(values))
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "Failed to substitute path placeholders in system message: %s; using raw prompt",
                exc,
            )
            return None
        return SystemMessage(
            content=substituted,
            additional_kwargs=sm.additional_kwargs,
            response_metadata=sm.response_metadata,
        )

    @override
    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelCallResult:
        new_sm = self._resolved_system_message(request)
        if new_sm is not None:
            request = request.override(system_message=new_sm)
        return handler(request)

    @override
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelCallResult:
        new_sm = self._resolved_system_message(request)
        if new_sm is not None:
            request = request.override(system_message=new_sm)
        return await handler(request)
