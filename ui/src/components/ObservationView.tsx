import { useEffect, useRef, useMemo } from "react";
import { useSessionStream } from "../hooks/useSessionStream";
import { TranscriptMessage, ToolCallGroup } from "./TranscriptMessage";
import type { TranscriptEntry } from "../hooks/useSessionStream";
import type { Session } from "../lib/types";

interface ObservationViewProps {
  session: Session;
}

/** Group consecutive tool_call entries together, leave others as-is. */
type DisplayItem =
  | { type: "entry"; entry: TranscriptEntry }
  | { type: "tool_group"; entries: TranscriptEntry[]; key: string };

function groupEntries(entries: TranscriptEntry[]): DisplayItem[] {
  const items: DisplayItem[] = [];
  let toolBuffer: TranscriptEntry[] = [];

  function flushTools() {
    if (toolBuffer.length > 0) {
      items.push({
        type: "tool_group",
        entries: [...toolBuffer],
        key: toolBuffer[0].id,
      });
      toolBuffer = [];
    }
  }

  for (const entry of entries) {
    if (entry.kind === "tool_call") {
      toolBuffer.push(entry);
    } else {
      flushTools();
      items.push({ type: "entry", entry });
    }
  }
  flushTools();

  return items;
}

export function ObservationView({ session }: ObservationViewProps) {
  const { entries, state } = useSessionStream(session.id);
  const scrollRef = useRef<HTMLDivElement>(null);

  const displayItems = useMemo(() => groupEntries(entries), [entries]);

  // Auto-scroll on new entries
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [displayItems]);

  return (
    <div className="flex h-full w-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-2">
        <span className="font-display text-sm text-text-muted">
          {session.routine_name ?? "Session"}
        </span>
        <span className="rounded-full bg-surface px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-text-dim">
          observing
        </span>
        {state === "streaming" && (
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-status-active" />
        )}
        <div className="flex-1" />
        <button
          disabled
          title="Drop-in available in a future update"
          className="rounded border border-border px-3 py-1 font-display text-xs text-text-dim opacity-50 cursor-not-allowed"
        >
          Drop In
        </button>
      </div>

      {/* Transcript */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto py-2">
        {entries.length === 0 && state === "streaming" && (
          <div className="flex h-full items-center justify-center">
            <span className="text-sm text-text-dim">
              Waiting for output...
            </span>
          </div>
        )}

        {displayItems.map((item) =>
          item.type === "tool_group" ? (
            <ToolCallGroup key={item.key} entries={item.entries} />
          ) : (
            <TranscriptMessage key={item.entry.id} entry={item.entry} />
          ),
        )}

        {state === "done" && (
          <div className="flex justify-center px-4 py-4">
            <span className="text-xs text-text-dim">Session completed</span>
          </div>
        )}

        {state === "error" && entries.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <span className="text-sm text-text-dim">
              No live stream available for this session
            </span>
          </div>
        )}

        {state === "error" && entries.length > 0 && (
          <div className="flex justify-center px-4 py-4">
            <span className="text-xs text-text-dim">Stream ended</span>
          </div>
        )}
      </div>
    </div>
  );
}
