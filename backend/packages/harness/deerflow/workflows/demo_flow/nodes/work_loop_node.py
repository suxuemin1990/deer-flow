"""Increment round counter; flag is_done when budget exhausted."""


def work_loop_node(state):
    current = state.get("current_round") or 0
    max_rounds = state.get("max_rounds") or 3
    if current >= max_rounds:
        return {"is_done": True}
    return {"current_round": current + 1, "is_done": False}
