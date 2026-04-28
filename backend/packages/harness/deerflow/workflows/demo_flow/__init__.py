"""demo_flow workflow — platform's first registered example.

Zero-LLM pipeline used to validate the platform mechanics (registry,
background runner, hint inbox, parent-thread emit). Real workflows like
training_explore replace the fake nodes with LLM + compute_cli calls.
"""

from pydantic import BaseModel, Field

from deerflow.workflows.demo_flow.agent import make_graph


class DemoFlowInput(BaseModel):
    task_name: str = Field(description="Human-readable task name")
    max_rounds: int = Field(default=3, ge=1, le=20, description="Number of fake rounds")


__all__ = ["DemoFlowInput", "make_graph"]
