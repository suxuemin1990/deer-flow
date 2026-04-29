"""Increment round counter; consume any new injected HumanMessages.

Hints arrive via two paths and are unified into ``state['messages']``:

1. **Inbox drain** (running-time injection, Bug 5 fix): we ask
   :mod:`hints_inbox` for any pending hints for our thread id. New
   hints are emitted as HumanMessages through this node's return value,
   so ``add_messages`` merges them into the next checkpoint and the
   running pregel itself is the writer (no overwrite race).

2. **Direct messages-channel writes** (terminal-state injection,
   inject_hint tool, etc.): land in ``state['messages']`` already; we
   just filter by ``state['_seen_msg_ids']`` to avoid re-feeding the
   inner LLM each tick.

Demo_flow does nothing semantic with hints — it only proves the
delivery pipe works end-to-end. Real workflows should feed the new
HumanMessages into their inner LLM and let the LLM react.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage
from langchain_core.runnables import RunnableConfig

from deerflow.workflows import hints_inbox


async def work_loop_node(state, config: RunnableConfig):
    current = state.get("current_round") or 0
    max_rounds = state.get("max_rounds") or 3
    if current >= max_rounds:
        return {"is_done": True}

    update: dict = {"current_round": current + 1, "is_done": False}

    # 1. Drain inbox: hints injected while running land here.
    child_tid = (config or {}).get("configurable", {}).get("thread_id", "")
    new_inbox_msgs: list[HumanMessage] = []
    if child_tid:
        drained = await hints_inbox.pop_all(child_tid)
        new_inbox_msgs = [
            HumanMessage(id=h.id, content=h.content) for h in drained
        ]
    if new_inbox_msgs:
        # add_messages reducer will merge into state.messages
        update["messages"] = new_inbox_msgs

    # 2. Filter messages channel for unseen HumanMessages (covers both
    #    the new inbox emissions above AND any terminal-state direct writes).
    seen = state.get("_seen_msg_ids") or set()
    msgs = state.get("messages") or []
    # Include the just-emitted inbox msgs in the "new" set even though
    # they aren't in state yet (the merge happens after this return).
    candidate_msgs = list(msgs) + new_inbox_msgs
    new_human_msgs = [
        m for m in candidate_msgs
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
