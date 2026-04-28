"""Render markdown report from accumulated history.

History entries are heterogeneous: ``{"round", "score"}`` (one per round
from poll_wait_node) plus optional ``{"round", "hints": [...]}`` entries
injected by work_loop_node when hints land mid-run. The report only tables
score-bearing entries; non-scored entries are filtered out.
"""


def final_node(state):
    history = state.get("history") or []
    scored = [e for e in history if "score" in e]
    rows = "\n".join(f"| {e['round']} | {e['score']} |" for e in scored)
    if scored:
        best = max(scored, key=lambda e: e["score"])
        footer = f"\n\n**Best round**: {best['round']} (score {best['score']})"
    else:
        footer = "\n\n*(no history)*"
    md = (
        f"## Exploration report — {state.get('task_name', '')}\n\n"
        f"| Round | Score |\n|---|---|\n{rows}{footer}"
    )
    return {"report_markdown": md}
