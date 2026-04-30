"""chat_demo workflow — bidirectional chat showcase.

Like demo_flow, but every round node emits an AIMessage so the workflow
detail page's chat panel actually shows back-and-forth: workflow says
"Round N: still searching", user can inject "try lr=0.001", next round
the workflow acknowledges with another AIMessage "Got 'try lr=0.001',
adjusting strategy." No real LLM — responses are templated. Useful for
demoing the chat UX without burning tokens.
"""

from pydantic import BaseModel, Field

from deerflow.workflows.chat_demo.agent import make_graph


class ChatDemoInput(BaseModel):
    task_name: str = Field(description="Human-readable task name")
    max_rounds: int = Field(
        default=5, ge=1, le=20, description="Number of fake rounds"
    )


__all__ = ["ChatDemoInput", "make_graph"]
