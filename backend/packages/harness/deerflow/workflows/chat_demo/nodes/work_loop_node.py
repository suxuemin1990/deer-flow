"""Work loop: tick + drain hint inbox + emit AIMessage reply.

Each round we:

1. Bump ``current_round``; if exceeded ``max_rounds``, mark done.
2. Drain ``hints_inbox`` for any user injection that arrived while the
   running task was sleeping in ``poll_wait``. Convert each hint into a
   ``HumanMessage`` (using the inbox's stable id so the frontend can
   dedupe optimistic bubbles) and emit them through the node return —
   the ``add_messages`` reducer merges them into the next checkpoint
   without racing the running pregel (Bug 5 fix).
3. Also pick up any HumanMessages already in ``state['messages']`` that
   we haven't seen yet (terminal-state direct writes via
   ``aupdate_state``). Track seen ids in ``_seen_msg_ids``.
4. Emit an AIMessage reply: if there were new hints, acknowledge them;
   otherwise just narrate progress for this round. Append a history
   entry with the round number and any hint contents.

This is a templated reply path — no LLM. Real workflows would feed the
collected ``new_human_msgs`` to an LLM here and emit the LLM's response
as the AIMessage instead.
"""

from __future__ import annotations

import random

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableConfig

from deerflow.workflows import hints_inbox


def _format_ack(hints: list[str]) -> str:
    if len(hints) == 1:
        return f"收到提示「{hints[0]}」,这一轮我会按这个方向调整策略。"
    joined = "、".join(f"「{h}」" for h in hints)
    return f"收到 {len(hints)} 条提示({joined}),将综合调整策略。"


def _format_progress(round_no: int, max_rounds: int) -> str:
    fillers = [
        "正在采样候选方案,暂未发现明显瓶颈。",
        "中间指标稳定,正在继续探索。",
        "本轮没有显著提升,将尝试更激进的策略。",
        "搜索空间收敛中,准备进入下一阶段。",
    ]
    return f"第 {round_no}/{max_rounds} 轮:{random.choice(fillers)}"


async def work_loop_node(state, config: RunnableConfig):
    current = state.get("current_round") or 0
    max_rounds = state.get("max_rounds") or 3

    if current >= max_rounds:
        return {"is_done": True}

    next_round = current + 1
    update: dict = {"current_round": next_round, "is_done": False}

    # Drain inbox first (running-time injection)
    child_tid = (config or {}).get("configurable", {}).get("thread_id", "")
    new_inbox_msgs: list[HumanMessage] = []
    if child_tid:
        drained = await hints_inbox.pop_all(child_tid)
        new_inbox_msgs = [
            HumanMessage(id=h.id, content=h.content) for h in drained
        ]

    # Identify any HumanMessages we haven't acknowledged yet (covers
    # both fresh inbox emissions AND terminal-state direct writes).
    seen = state.get("_seen_msg_ids") or set()
    candidate_msgs = list(state.get("messages") or []) + new_inbox_msgs
    new_human_msgs = [
        m for m in candidate_msgs
        if isinstance(m, HumanMessage) and getattr(m, "id", None) not in seen
    ]

    # Build the AI reply for this round.
    if new_human_msgs:
        contents = [m.content for m in new_human_msgs]
        reply_text = _format_ack(contents)
    else:
        reply_text = _format_progress(next_round, max_rounds)
    reply = AIMessage(content=reply_text)

    # Compose messages update: inbox HumanMessages + AI reply (in order).
    msgs_out = new_inbox_msgs + [reply]
    update["messages"] = msgs_out

    # History entry
    entry: dict = {"round": next_round, "reply": reply_text}
    if new_human_msgs:
        entry["hints"] = [m.content for m in new_human_msgs]
    update["history"] = [entry]

    if new_human_msgs:
        update["_seen_msg_ids"] = seen | {
            m.id for m in new_human_msgs if getattr(m, "id", None)
        }

    return update
