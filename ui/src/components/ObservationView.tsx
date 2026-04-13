import { useEffect, useRef, useMemo } from "react";
import { useSessionStream } from "../hooks/useSessionStream";
import {
  MessageList,
  classifyMessages,
  type DisplayMessage,
} from "./MessageList";
import type { Session } from "../lib/types";

interface ObservationViewProps {
  session: Session;
}

export function ObservationView({ session }: ObservationViewProps) {
  const { entries, state } = useSessionStream(session.id);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Feed SSE entries through classifyMessages so live observation uses
  // the same tool_use / tool_result / thinking renderer as the chat
  // history view. Entries arrive with marker-tagged content (e.g.
  // "[tool_use:toolu_abc] Task({...})") and classifyMessages parses
  // them into DisplayMessages grouped into ToolCallGroup cards.
  const messages: DisplayMessage[] = useMemo(() => {
    const raw = entries.map((e) => {
      let content = e.content;
      // Re-synthesize the marker prefix that classifyMessages expects.
      // Streamed text/thinking markers are stripped by the adapter
      // already; tool_use / tool_result content arrives with markers.
      if (e.kind === "thinking" && !content.startsWith("[thinking]")) {
        content = `[thinking] ${content}`;
      }
      return {
        id: e.id,
        content,
        role: "assistant" as const,
        created_at: new Date(e.timestamp).toISOString(),
      };
    });
    return classifyMessages(raw);
  }, [entries]);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

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

        <MessageList messages={messages} />

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
