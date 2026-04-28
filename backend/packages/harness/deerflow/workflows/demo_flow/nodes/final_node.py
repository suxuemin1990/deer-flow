"""Render markdown report from accumulated history."""


def final_node(state):
    history = state.get("history") or []
    rows = "\n".join(f"| {e['round']} | {e['score']} |" for e in history)
    if history:
        best = max(history, key=lambda e: e["score"])
        footer = f"\n\n**Best round**: {best['round']} (score {best['score']})"
    else:
        footer = "\n\n*(no history)*"
    md = (
        f"## Exploration report — {state.get('task_name', '')}\n\n"
        f"| Round | Score |\n|---|---|\n{rows}{footer}"
    )
    return {"report_markdown": md}
