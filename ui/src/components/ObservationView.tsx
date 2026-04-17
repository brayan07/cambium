import { useEffect, useRef } from "react";
import { useObservationStream } from "../hooks/useObservationStream";
import { MessageList } from "./MessageList";
import type { Session } from "../lib/types";

interface ObservationViewProps {
  session: Session;
}

export function ObservationView({ session }: ObservationViewProps) {
  const { messages, mode } = useObservationStream(session.id);
  const scrollRef = useRef<HTMLDivElement>(null);

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
        {mode === "streaming" && (
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-status-active" />
        )}
        {mode === "polling" && (
          <span className="rounded-full bg-status-warning/15 px-2 py-0.5 text-[10px] font-medium text-status-warning">
            Polling for updates
          </span>
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
        {messages.length === 0 && (mode === "streaming" || mode === "connecting") && (
          <div className="flex h-full items-center justify-center">
            <span className="text-sm text-text-dim">
              Waiting for output...
            </span>
          </div>
        )}

        <MessageList messages={messages} />

        {mode === "done" && (
          <div className="flex justify-center px-4 py-4">
            <span className="text-xs text-text-dim">Session completed</span>
          </div>
        )}
      </div>
    </div>
  );
}
