"""Run a workflow graph in the background, emit results to the parent thread.

Lifecycle owned here:
  1. compile graph with the shared checkpointer
  2. invoke with caller-provided params + child_thread_id + parent_thread_id
  3. on success: read report_field from final state, emit to parent
  4. on failure: write _error to child state, emit error message to parent

Before each emit we wait for the parent thread's RunManager to report no
in-flight runs. Without this gate, when a fast workflow finishes while
lead_agent is still streaming its tool-result reply, the emit's
``aupdate_state`` writes a checkpoint that branches off lead_agent's last
visible checkpoint; lead_agent's next ``loop`` write picks the same parent
and overwrites the emit. The user sees the report disappear.

Caller (start_workflow tool) wraps this in asyncio.create_task and tracks
the task in a registry so cancel_workflow can cancel it.
"""

from __future__ import annotations

import asyncio
import logging
import time

from langgraph.checkpoint.base import BaseCheckpointSaver

from deerflow.workflows.emit import emit_to_parent_thread
from deerflow.workflows.finish_stamp import stamp_parent_finish
from deerflow.workflows.registry import WorkflowSpec

logger = logging.getLogger(__name__)

# How long to wait for parent thread's last run to drain before emitting
# anyway. 60s covers a normal LLM streaming window with margin; if the
# parent thread is genuinely stuck we still want the report on disk so
# operators can inspect it via /threads/{tid}/state.
_DEFAULT_WAIT_TIMEOUT_S = 60.0
_DEFAULT_POLL_INTERVAL_S = 0.25


async def _wait_for_parent_idle(
    parent_thread_id: str,
    *,
    timeout_s: float = _DEFAULT_WAIT_TIMEOUT_S,
    poll_interval_s: float = _DEFAULT_POLL_INTERVAL_S,
) -> None:
    """Poll RunManager until the parent thread has no in-flight runs.

    Degrades gracefully: if no RunManager is registered (unit tests,
    langgraph dev mode, etc.), returns immediately. Stops polling once
    *timeout_s* elapses regardless of state — caller should still proceed
    to emit; a stuck parent shouldn't block the workflow report forever.
    """
    # Lazy import to avoid extending workflows.background's module-level
    # dependency graph; importing run_manager_singleton at top-level pulls
    # in deerflow.runtime/__init__ early enough to participate in a known
    # circular-import cycle through agents/factory/tools.builtins.
    from deerflow.runtime.run_manager_singleton import try_get_default_run_manager

    mgr = try_get_default_run_manager()
    if mgr is None:
        return

    deadline = time.monotonic() + timeout_s
    while True:
        try:
            inflight = await mgr.has_inflight(parent_thread_id)
        except Exception:
            logger.exception(
                "RunManager.has_inflight raised for parent %s; emitting anyway",
                parent_thread_id,
            )
            return

        if not inflight:
            return
        if time.monotonic() >= deadline:
            logger.warning(
                "Parent thread %s still has in-flight run after %.1fs; "
                "emitting anyway (workflow report may race with agent output)",
                parent_thread_id,
                timeout_s,
            )
            return

        await asyncio.sleep(poll_interval_s)


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
        await _wait_for_parent_idle(parent_thread_id)
        await stamp_parent_finish(parent_thread_id)
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
        await _wait_for_parent_idle(parent_thread_id)
        await stamp_parent_finish(parent_thread_id)
        try:
            await emit_to_parent_thread(
                parent_thread_id,
                f"[workflow:{spec.name}] failed: {err}",
                checkpointer=checkpointer,
            )
        except Exception:
            logger.exception("could not emit failure to parent %s", parent_thread_id)
        return

    # Success path. We always stamp the parent (so the frontend can show
    # the "unread finish" red dot for any terminal event); we only emit a
    # report message if the workflow actually produced one.
    try:
        final_state = await graph.aget_state(cfg)
        report = final_state.values.get(spec.report_field)
        await _wait_for_parent_idle(parent_thread_id)
        await stamp_parent_finish(parent_thread_id)
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
