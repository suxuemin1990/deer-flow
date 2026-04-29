"""Increment round counter; consume any new injected HumanMessages.

Hints arrive via the workflow's ``messages`` channel (populated by user
injection in the Workflow Hub UI or by the lead agent's ``inject_hint``
tool). On each tick we filter ``state['messages']`` for HumanMessages
whose id is not yet in ``state['_seen_msg_ids']``, stamp their content
into ``history``, and update the seen-set.

Demo_flow does nothing semantic with hints — it only proves the
messages-channel delivery pipe works end-to-end. Real workflows should
feed the new HumanMessages into their inner LLM and let the LLM react.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig


async def work_loop_node(state, config: RunnableConfig):
    current = state.get("current_round") or 0
    max_rounds = state.get("max_rounds") or 3
    if current >= max_rounds:
        return {"is_done": True}

    update: dict = {"current_round": current + 1, "is_done": False}

    seen = state.get("_seen_msg_ids") or set()
    msgs = state.get("messages") or []
    new_human_msgs = [
        m for m in msgs
        if isinstance(m, HumanMessage) and getattr(m, "id", None) not in seen
    ]
    if new_human_msgs:
        update["history"] = [{
            "round": current + 1,
            "hints": [m.content for m in new_human_msgs],
        }]
        update["_seen_msg_ids"] = seen | {
            m.id for m in new_human_msgs if getattr(m, "id", None)
        }
    return update
