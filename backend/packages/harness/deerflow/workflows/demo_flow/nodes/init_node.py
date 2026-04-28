"""Reset per-run counter; supports re-invoke on same thread."""


def init_node(state):
    return {"current_round": 0}
