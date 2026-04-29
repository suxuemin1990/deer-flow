"use client";

import { useEffect, useRef } from "react";

interface Props {
  /** Workflow state values; usually `state.values` from the polled state endpoint. */
  values: Record<string, unknown>;
  /** Spec field names to render as timelines. For demo-flow this is `["history"]`. */
  fields: string[];
}

interface Row {
  fieldName: string;
  index: number;
  isLatest: boolean;
  entry: Record<string, unknown>;
}

/**
 * Vertical timeline panel for non-LLM workflows (option A in the
 * 2026-04-29 design). One row per entry in each spec-declared
 * progress_timeline_field. Fields not on the spec list are ignored.
 *
 * Returns null if there are no fields to render.
 */
export function ProgressTimeline({ values, fields }: Props) {
  const listRef = useRef<HTMLDivElement>(null);

  const rows: Row[] = [];
  for (const f of fields) {
    const arr = values[f];
    if (!Array.isArray(arr)) continue;
    for (let i = 0; i < arr.length; i++) {
      const entry = arr[i];
      if (entry && typeof entry === "object") {
        rows.push({
          fieldName: f,
          index: i,
          isLatest: i === arr.length - 1,
          entry: entry as Record<string, unknown>,
        });
      }
    }
  }

  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [rows.length]);

  if (fields.length === 0) return null;
  if (rows.length === 0) {
    return (
      <div className="text-muted-foreground border-b p-3 text-center text-sm">
        No progress yet.
      </div>
    );
  }

  return (
    <div className="border-b">
      <div className="text-muted-foreground px-3 pt-2 text-xs uppercase tracking-wide">
        Progress
      </div>
      <div
        ref={listRef}
        className="max-h-[40vh] space-y-1.5 overflow-auto p-3"
      >
        {rows.map((r) => (
          <TimelineRow key={`${r.fieldName}-${r.index}`} row={r} />
        ))}
      </div>
    </div>
  );
}

function TimelineRow({ row }: { row: Row }) {
  const isHint =
    Array.isArray(row.entry.hints) && row.entry.hints.length > 0;
  const segments: string[] = [];
  for (const [k, v] of Object.entries(row.entry)) {
    if (k === "hints") continue;
    segments.push(formatKV(k, v));
  }
  if (isHint) {
    const hints = (row.entry.hints as unknown[]).map(String).join(" / ");
    segments.push(`💬 ${hints}`);
  }

  return (
    <div className="flex items-start gap-2 text-sm">
      <span
        data-testid={
          row.isLatest ? "timeline-dot-filled" : "timeline-dot-hollow"
        }
        className={`mt-1.5 size-2 shrink-0 rounded-full ${
          row.isLatest ? "bg-primary" : "border-muted-foreground border"
        }`}
      />
      <span className="text-foreground/80 flex-1 font-mono text-xs">
        {segments.join(" · ")}
      </span>
    </div>
  );
}

function formatKV(k: string, v: unknown): string {
  if (v === null || v === undefined) return `${k}=∅`;
  if (typeof v === "string" || typeof v === "number" || typeof v === "boolean") {
    return `${k}=${v}`;
  }
  try {
    return `${k}=${JSON.stringify(v)}`;
  } catch {
    return `${k}=<unserializable>`;
  }
}
