"""Final node: emit closing AIMessage + render markdown report."""

from __future__ import annotations

from langchain_core.messages import AIMessage


def final_node(state):
    history = state.get("history") or []
    task = state.get("task_name") or ""
    rounds = len(history)

    rows = "\n".join(
        f"| {e['round']} | {e.get('reply', '')[:60]} |" for e in history
    )

    hint_lines = [
        f"- 第 {e['round']} 轮:{', '.join(e['hints'])}"
        for e in history
        if e.get("hints")
    ]
    hint_block = (
        "\n\n**收到的提示**\n\n" + "\n".join(hint_lines)
        if hint_lines
        else "\n\n_(本次运行未收到任何用户提示)_"
    )

    md = (
        f"## 执行报告 — {task}\n\n"
        f"完成 **{rounds}** 轮调整。\n\n"
        f"### 每轮回复摘要\n\n"
        f"| Round | Reply |\n|---|---|\n{rows}"
        f"{hint_block}"
    )

    closing = AIMessage(
        content=f"任务「{task}」已完成,共 {rounds} 轮。完整报告请见上方汇总。"
    )

    return {"report_markdown": md, "messages": [closing]}
