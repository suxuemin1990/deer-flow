"""Render the workflow catalog as a markdown section for lead_agent's prompt."""

from __future__ import annotations

from typing import get_args, get_origin

from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from deerflow.workflows.registry import WorkflowRegistry, WorkflowSpec

_HEADER = (
    "## Available Workflows\n\n"
    "You can start long-running background workflows via "
    "start_workflow(name, params). Then control them with inject_hint, "
    "cancel_workflow, get_workflow_progress (each takes thread_id from "
    "start_workflow's return).\n"
)


def _format_field(name: str, info) -> str:
    annotation = info.annotation
    origin = get_origin(annotation)
    if origin is None:
        type_name = getattr(annotation, "__name__", str(annotation))
    else:
        args = ", ".join(getattr(a, "__name__", str(a)) for a in get_args(annotation))
        type_name = f"{origin.__name__}[{args}]"
    required = info.is_required()
    parts = [f"{type_name}"]
    if required:
        parts.append("required")
    elif info.default is not PydanticUndefined:
        parts.append(f"default={info.default!r}")
    desc = info.description or ""
    return f"  - {name} ({', '.join(parts)}){': ' + desc if desc else ''}"


def _render_one(spec: WorkflowSpec) -> str:
    lines = [f"### {spec.name} — {spec.description.strip()}"]
    schema: type[BaseModel] = spec.input_schema
    lines.append("Params:")
    for fname, finfo in schema.model_fields.items():
        lines.append(_format_field(fname, finfo))
    if spec.hint_behavior_doc.strip():
        lines.append(f"Hint behavior: {spec.hint_behavior_doc.strip()}")
    return "\n".join(lines)


def render_workflow_catalog(registry: WorkflowRegistry) -> str:
    if not registry.all():
        return _HEADER + "\n_No workflows registered._"
    sections = [_render_one(s) for s in registry.all()]
    return _HEADER + "\n" + "\n\n".join(sections)
