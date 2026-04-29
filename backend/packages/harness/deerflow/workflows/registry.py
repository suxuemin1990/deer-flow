"""Workflow registry — loads workflow definitions from yaml/dicts at startup.

Each entry resolves ``factory`` (callable taking ``checkpointer``) and
``input_schema`` (Pydantic ``BaseModel``) eagerly. Failures are logged and
skipped so a single broken entry doesn't kill gateway startup.
"""

from __future__ import annotations

import importlib
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)


def _resolve(spec: str) -> Any:
    """Resolve ``module:attr`` to the live object."""
    module_name, _, attr = spec.partition(":")
    if not module_name or not attr:
        raise ValueError(f"Invalid spec {spec!r}: expected 'module:attr'")
    mod = importlib.import_module(module_name)
    obj = getattr(mod, attr, None)
    if obj is None:
        raise AttributeError(f"{attr!r} not found in {module_name!r}")
    return obj


@dataclass(frozen=True)
class WorkflowSpec:
    name: str
    description: str
    factory: Callable[..., Any]
    input_schema: type[BaseModel]
    done_field: str
    report_field: str
    progress_fields: list[str] = field(default_factory=list)
    hint_behavior_doc: str = ""
    accepts_chat: bool = False


class WorkflowRegistry:
    """In-memory registry; constructed once at gateway lifespan."""

    def __init__(self, specs: list[WorkflowSpec], failures: list[tuple[str, str]]) -> None:
        self._specs = {s.name: s for s in specs}
        self._failures = failures

    # ------------------------------------------------------------------
    # Loaders

    @classmethod
    def load_from_dicts(cls, items: list[dict[str, Any]]) -> WorkflowRegistry:
        specs: list[WorkflowSpec] = []
        failures: list[tuple[str, str]] = []
        for item in items:
            name = item.get("name", "<unnamed>")
            try:
                factory = _resolve(item["factory"])
                if not callable(factory):
                    raise TypeError(f"factory {item['factory']!r} is not callable")
                input_schema = _resolve(item["input_schema"])
                if not (isinstance(input_schema, type) and issubclass(input_schema, BaseModel)):
                    raise TypeError(
                        f"input_schema {item['input_schema']!r} must be a pydantic BaseModel subclass"
                    )
                specs.append(WorkflowSpec(
                    name=item["name"],
                    description=item["description"],
                    factory=factory,
                    input_schema=input_schema,
                    done_field=item["done_field"],
                    report_field=item["report_field"],
                    progress_fields=list(item.get("progress_fields") or []),
                    hint_behavior_doc=item.get("hint_behavior_doc") or "",
                    accepts_chat=bool(item.get("accepts_chat", False)),
                ))
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                logger.error("workflow registry: skipping %r — %s", name, msg)
                failures.append((name, msg))
        return cls(specs, failures)

    @classmethod
    def load_from_app_config(cls) -> WorkflowRegistry:
        from deerflow.config import get_app_config

        cfg = get_app_config()
        items = getattr(cfg, "workflows", None) or []
        # Pydantic-config items may already be objects; normalize to dicts.
        normalized = [item.model_dump() if hasattr(item, "model_dump") else dict(item) for item in items]
        return cls.load_from_dicts(normalized)

    # ------------------------------------------------------------------
    # Accessors

    def names(self) -> list[str]:
        return list(self._specs.keys())

    def get(self, name: str) -> WorkflowSpec:
        if name not in self._specs:
            raise KeyError(f"Workflow {name!r} is not registered")
        return self._specs[name]

    def has(self, name: str) -> bool:
        return name in self._specs

    def all(self) -> list[WorkflowSpec]:
        return list(self._specs.values())

    def failed(self) -> list[tuple[str, str]]:
        return list(self._failures)
