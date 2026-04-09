import { useEffect, useRef, useMemo } from "react";
import { useMessages } from "../hooks/useMessages";
import { MessageList, type DisplayMessage } from "./MessageList";
import type { Session } from "../lib/types";

interface SessionHistoryProps {
  session: Session;
  onResume: (session: Session) => void;
}

export function SessionHistory({ session, onResume }: SessionHistoryProps) {
  const { data: messages, isLoading } = useMessages(session.id);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Map REST messages to the shared DisplayMessage shape
  const displayMessages: DisplayMessage[] = useMemo(
    () =>
      (messages ?? []).map((m) => ({
        id: m.id,
        content: m.content,
        role: m.role as DisplayMessage["role"],
        timestamp: new Date(m.created_at).getTime(),
      })),
    [messages],
  );

  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [displayMessages]);

  return (
    <div className="flex h-full w-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-2">
        <span className="font-display text-sm text-text-muted">
          {session.routine_name ?? "Session"}
        </span>
        <span className="rounded-full bg-surface px-2 py-0.5 text-[10px] font-medium uppercase tracking-wider text-text-dim">
          {session.status}
        </span>
        <div className="flex-1" />
        <span className="text-[10px] text-text-dim">
          {new Date(session.updated_at).toLocaleString()}
        </span>
        {session.status === "completed" && (
          <button
            onClick={() => onResume(session)}
            className="rounded border border-accent bg-accent-dim px-3 py-1 font-display text-xs text-accent transition-colors hover:bg-accent hover:text-base"
          >
            Resume
          </button>
        )}
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto py-2">
        {isLoading && (
          <div className="flex h-full items-center justify-center">
            <span className="text-sm text-text-dim">Loading messages...</span>
          </div>
        )}

        {!isLoading && displayMessages.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <span className="text-sm text-text-dim">
              No messages recorded for this session
            </span>
          </div>
        )}

        <MessageList messages={displayMessages} />
      </div>
    </div>
  );
}
