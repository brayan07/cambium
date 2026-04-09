import { useEffect, useRef } from "react";
import { useMessages } from "../hooks/useMessages";
import type { Session } from "../lib/types";

interface SessionHistoryProps {
  session: Session;
  onResume: (session: Session) => void;
}

export function SessionHistory({ session, onResume }: SessionHistoryProps) {
  const { data: messages, isLoading } = useMessages(session.id);
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

        {!isLoading && (!messages || messages.length === 0) && (
          <div className="flex h-full items-center justify-center">
            <span className="text-sm text-text-dim">
              No messages recorded for this session
            </span>
          </div>
        )}

        {messages?.map((msg) => (
          <HistoryMessage key={msg.id} message={msg} />
        ))}
      </div>
    </div>
  );
}

function HistoryMessage({ message }: { message: { role: string; content: string; created_at: string } }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isTool = message.role === "tool";

  if (isSystem) {
    return (
      <div className="flex justify-center px-4 py-1">
        <span className="text-xs text-text-dim italic">{message.content}</span>
      </div>
    );
  }

  if (isTool) {
    return (
      <div className="flex px-4 py-0.5">
        <span className="font-mono text-[11px] text-text-dim">
          <span className="text-accent">{">"}</span>{" "}
          {message.content.length > 200
            ? message.content.slice(0, 200) + "..."
            : message.content}
        </span>
      </div>
    );
  }

  return (
    <div
      className={`group flex px-4 py-2 ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[80%] whitespace-pre-wrap font-mono text-xs leading-relaxed ${
          isUser
            ? "rounded bg-accent-dim px-3 py-2 text-accent"
            : "text-text"
        }`}
      >
        {message.content}
        <span className="ml-2 hidden text-[10px] text-text-dim group-hover:inline">
          {new Date(message.created_at).toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}
