"""Verify SandboxMiddleware is not present in the lead agent middleware chain."""
from deerflow.agents.middlewares.tool_error_handling_middleware import build_lead_runtime_middlewares


def test_chain_omits_sandbox_middleware():
    chain = build_lead_runtime_middlewares(lazy_init=True)
    cls_names = {type(m).__name__ for m in chain}
    assert "SandboxMiddleware" not in cls_names
    # ThreadDataMiddleware stays
    assert "ThreadDataMiddleware" in cls_names
