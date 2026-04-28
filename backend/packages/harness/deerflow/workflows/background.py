"""Run a workflow graph in the background, emit results to the parent thread.

Lifecycle owned here:
  1. compile graph with the shared checkpointer
  2. invoke with caller-provided params + child_thread_id + parent_thread_id
  3. on success: read report_field from final state, emit to parent
  4. on failure: write _error to child state, emit error message to parent

Caller (start_workflow tool) wraps this in asyncio.create_task and tracks
the task in a registry so cancel_workflow can cancel it.
"""

from __future__ import annotations

import asyncio
import logging

from langgraph.checkpoint.base import BaseCheckpointSaver

from deerflow.workflows.emit import emit_to_parent_thread
from deerflow.workflows.registry import WorkflowSpec

logger = logging.getLogger(__name__)


async def run_workflow_background(
    *,
    spec: WorkflowSpec,
    params: dict,
    child_thread_id: str,
    parent_thread_id: str,
    checkpointer: BaseCheckpointSaver,
) -> None:
    """Run *spec* once on *child_thread_id*, emit to *parent_thread_id*.

    Never raises — all exceptions are caught, written to state and parent
    thread (best effort) and re-logged.
    """
    graph = spec.factory(checkpointer=checkpointer)
    cfg = {"configurable": {"thread_id": child_thread_id}}
    initial = {**params, "_parent_thread_id": parent_thread_id}

    try:
        await graph.ainvoke(initial, config=cfg)
    except asyncio.CancelledError:
        err = "CancelledError: workflow cancelled by user"
        logger.info("workflow %s cancelled on %s", spec.name, child_thread_id)
        try:
            await graph.aupdate_state(
                config=cfg,
                values={"_error": err, spec.done_field: True},
            )
        except Exception:
            logger.exception("could not write _error after cancel on %s", child_thread_id)
        try:
            await emit_to_parent_thread(
                parent_thread_id,
                f"[workflow:{spec.name}] cancelled by user",
                checkpointer=checkpointer,
            )
        except Exception:
            logger.exception("could not emit cancel notice to parent %s", parent_thread_id)
        return
    except Exception as exc:
        err = f"{type(exc).__name__}: {exc}"
        logger.exception("workflow %s failed on %s", spec.name, child_thread_id)
        # Best-effort: write _error + done flag to child state
        try:
            await graph.aupdate_state(
                config=cfg,
                values={"_error": err, spec.done_field: True},
            )
        except Exception:
            logger.exception("could not write _error to %s", child_thread_id)
        # Best-effort: emit failure to parent
        try:
            await emit_to_parent_thread(
                parent_thread_id,
                f"[workflow:{spec.name}] failed: {err}",
                checkpointer=checkpointer,
            )
        except Exception:
            logger.exception("could not emit failure to parent %s", parent_thread_id)
        return

    # Success path
    try:
        final_state = await graph.aget_state(cfg)
        report = final_state.values.get(spec.report_field)
        if report:
            await emit_to_parent_thread(
                parent_thread_id,
                f"[workflow:{spec.name}] done\n\n{report}",
                checkpointer=checkpointer,
            )
        else:
            logger.warning(
                "workflow %s on %s finished but report_field %r is empty",
                spec.name, child_thread_id, spec.report_field,
            )
    except Exception:
        logger.exception("could not emit success report for %s", child_thread_id)
