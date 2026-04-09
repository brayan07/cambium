import { useEffect, useRef, useMemo, useState } from "react";
import { useMessages, type Message } from "../hooks/useMessages";
import type { Session } from "../lib/types";

interface SessionHistoryProps {
  session: Session;
  onResume: (session: Session) => void;
}

type DisplayItem =
  | { type: "message"; message: Message }
  | { type: "tool_group"; messages: Message[]; key: string };

function groupMessages(messages: Message[]): DisplayItem[] {
  const items: DisplayItem[] = [];
  let toolBuffer: Message[] = [];

  function flushTools() {
    if (toolBuffer.length > 0) {
      items.push({
        type: "tool_group",
        messages: [...toolBuffer],
        key: toolBuffer[0].id,
      });
      toolBuffer = [];
    }
  }

  for (const msg of messages) {
    if (msg.role === "tool") {
      toolBuffer.push(msg);
    } else {
      flushTools();
      items.push({ type: "message", message: msg });
    }
  }
  flushTools();

  return items;
}

export function SessionHistory({ session, onResume }: SessionHistoryProps) {
  const { data: messages, isLoading } = useMessages(session.id);
  const scrollRef = useRef<HTMLDivElement>(null);

  const displayItems = useMemo(
    () => groupMessages(messages ?? []),
    [messages],
  );

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

        {!isLoading && displayItems.length === 0 && (
          <div className="flex h-full items-center justify-center">
            <span className="text-sm text-text-dim">
              No messages recorded for this session
            </span>
          </div>
        )}

        {displayItems.map((item) =>
          item.type === "tool_group" ? (
            <ToolCallGroup key={item.key} messages={item.messages} />
          ) : (
            <HistoryMessage key={item.message.id} message={item.message} />
          ),
        )}
      </div>
    </div>
  );
}

function ToolCallGroup({ messages }: { messages: Message[] }) {
  const [expanded, setExpanded] = useState(false);

  const label =
    messages.length === 1
      ? truncate(messages[0].content, 60)
      : `${messages.length} tool calls`;

  return (
    <div className="px-4 py-0.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1.5 font-mono text-[11px] text-text-dim transition-colors hover:text-text-muted"
      >
        <span
          className={`inline-block transition-transform ${expanded ? "rotate-90" : ""}`}
        >
          &#9656;
        </span>
        <span className="text-accent">{">"}</span>
        <span>{label}</span>
      </button>
      {expanded && (
        <div className="ml-5 mt-0.5 border-l border-border pl-2">
          {messages.map((msg) => (
            <div
              key={msg.id}
              className="whitespace-pre-wrap font-mono text-[11px] text-text-dim py-0.5"
            >
              {truncate(msg.content, 200)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function HistoryMessage({ message }: { message: Message }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="flex justify-center px-4 py-1">
        <span className="text-xs text-text-dim italic">{message.content}</span>
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

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "..." : s;
}
