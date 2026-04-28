"""Increment round counter; consume any pending hints into history.

Hints arrive via :mod:`deerflow.workflows.hints_inbox` (a process-local inbox
populated by the ``inject_hint`` tool). We drain them at the start of each
round and stamp them into ``history`` next to the round entry, so an
operator inspecting the final report can see when a hint landed.

Demo_flow does nothing semantic with hints — it only proves the inbox →
node delivery pipe works end-to-end. Real workflows should actually adjust
behavior based on the drained hints.
"""

from __future__ import annotations

from langchain_core.runnables import RunnableConfig

from deerflow.workflows.hints_inbox import pop_hints


async def work_loop_node(state, config: RunnableConfig):
    current = state.get("current_round") or 0
    max_rounds = state.get("max_rounds") or 3
    if current >= max_rounds:
        return {"is_done": True}

    update: dict = {"current_round": current + 1, "is_done": False}

    thread_id = (config or {}).get("configurable", {}).get("thread_id")
    if thread_id:
        hints = await pop_hints(thread_id)
        if hints:
            update["history"] = [{"round": current + 1, "hints": hints}]
    return update
