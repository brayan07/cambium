import { useState, useMemo } from "react";

/** Unified message shape that both SSE entries and REST messages can provide. */
export interface DisplayMessage {
  id: string;
  content: string;
  role: "assistant" | "user" | "system" | "tool" | "thinking";
  timestamp: number;
}

type DisplayItem =
  | { type: "message"; message: DisplayMessage }
  | { type: "tool_group"; messages: DisplayMessage[]; key: string };

function groupMessages(messages: DisplayMessage[]): DisplayItem[] {
  const items: DisplayItem[] = [];
  let toolBuffer: DisplayMessage[] = [];

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

export function MessageList({ messages }: { messages: DisplayMessage[] }) {
  const items = useMemo(() => groupMessages(messages), [messages]);

  return (
    <>
      {items.map((item) =>
        item.type === "tool_group" ? (
          <ToolCallGroup key={item.key} messages={item.messages} />
        ) : (
          <MessageBubble key={item.message.id} message={item.message} />
        ),
      )}
    </>
  );
}

function ToolCallGroup({ messages }: { messages: DisplayMessage[] }) {
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

function MessageBubble({ message }: { message: DisplayMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";
  const isThinking = message.role === "thinking";

  if (isSystem) {
    return (
      <div className="flex justify-center px-4 py-1">
        <span className="text-xs text-text-dim italic">{message.content}</span>
      </div>
    );
  }

  if (isThinking) {
    return (
      <div className="px-4 py-1">
        <div className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-dim italic">
          {message.content}
        </div>
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
          {new Date(message.timestamp).toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + "..." : s;
}
