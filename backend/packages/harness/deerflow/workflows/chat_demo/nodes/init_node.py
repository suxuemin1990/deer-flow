"""Init: emit an opening AIMessage and reset round counter."""

from __future__ import annotations

from langchain_core.messages import AIMessage


def init_node(state):
    task = state.get("task_name") or "the task"
    max_rounds = state.get("max_rounds") or 3
    greeting = AIMessage(
        content=(
            f"开始执行 **{task}**(共 {max_rounds} 轮)。"
            "运行期间你可以随时给我发提示,我会在下一轮回应。"
        )
    )
    return {"current_round": 0, "messages": [greeting]}
