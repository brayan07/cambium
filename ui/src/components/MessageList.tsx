import { useState, useMemo } from "react";
import Markdown from "react-markdown";
import remarkGfm from "remark-gfm";

/** Unified message shape that both SSE entries and REST messages can provide. */
export interface DisplayMessage {
  id: string;
  content: string;
  role: "assistant" | "user" | "system" | "tool" | "thinking" | "meta";
  timestamp: number;
  /** Base64 data URLs for images attached to this message (user messages only). */
  images?: string[];
  /** For tool messages: "call" (tool_use) or "result" (tool_result). */
  toolType?: "call" | "result";
  /** For tool messages: the tool_use_id linking a call to its result. */
  toolCallId?: string;
}

/**
 * Parse raw API messages into properly classified DisplayMessages.
 * The Cambium message API uses inline markers like [tool_use], [tool_result:...],
 * [thinking], [rate_limit], [system:init] rather than separate roles.
 */
export function classifyMessages(
  raw: Array<{ id: string; content: string; role: string; created_at: string }>,
): DisplayMessage[] {
  const result: DisplayMessage[] = [];

  for (const m of raw) {
    const ts = new Date(m.created_at).getTime();

    // Rate limit events → meta (hidden by default)
    if (m.role === "rate_limit_event" || m.content.startsWith("[rate_limit]")) {
      continue; // skip entirely — noise
    }

    // System init messages → meta
    if (m.content.startsWith("[system:")) {
      continue; // skip — internal bookkeeping
    }

    // The adapter may join multiple content blocks (tool_use, tool_result,
    // thinking, text) into one message separated by newlines. Split them
    // into individual DisplayMessages for proper grouping and display.
    const blocks = _splitBlocks(m.content);
    if (blocks.length > 1) {
      for (let i = 0; i < blocks.length; i++) {
        const block = blocks[i];
        const blockId = `${m.id}-${i}`;
        _classifyBlock(blockId, block, m.role, ts, result);
      }
      continue;
    }

    _classifyBlock(m.id, m.content, m.role, ts, result);
  }

  return result;
}

/** Split a message that may contain multiple [tool_use]/[tool_result]/[thinking] blocks. */
function _splitBlocks(content: string): string[] {
  const parts = content.split(/\n(?=\[(?:tool_use[^\]]*|tool_result[^\]]*|thinking)\]\s)/);
  return parts.filter((p) => p.trim());
}

/** Classify a single content block into a DisplayMessage. */
function _classifyBlock(
  id: string,
  content: string,
  role: string,
  ts: number,
  result: DisplayMessage[],
): void {
  // Tool use: [tool_use:ID] or legacy [tool_use]
  const toolUseMatch = content.match(/^\[tool_use(?::([^\]]*))?\]\s*/);
  if (toolUseMatch) {
    const cleaned = content.slice(toolUseMatch[0].length);
    const toolCallId = toolUseMatch[1] || undefined;
    result.push({ id, content: cleaned, role: "tool", timestamp: ts, toolType: "call", toolCallId });
    return;
  }

  // Tool result: [tool_result:ID] or [tool_result]
  const toolResultMatch = content.match(/^\[tool_result(?::([^\]]*))?\]\s*/);
  if (toolResultMatch) {
    const cleaned = content.slice(toolResultMatch[0].length);
    const toolCallId = toolResultMatch[1] || undefined;
    result.push({ id, content: cleaned, role: "tool", timestamp: ts, toolType: "result", toolCallId });
    return;
  }

  // Thinking
  if (content.startsWith("[thinking]")) {
    const cleaned = content.replace(/^\[thinking\]\s*/, "");
    result.push({ id, content: cleaned, role: "thinking", timestamp: ts });
    return;
  }

  // Regular assistant or user message
  const displayRole: DisplayMessage["role"] =
    role === "user" ? "user" : role === "system" ? "system" : "assistant";
  result.push({ id, content, role: displayRole, timestamp: ts });
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
    <div className="flex flex-col">
      {items.map((item) =>
        item.type === "tool_group" ? (
          <ToolCallGroup key={item.key} messages={item.messages} />
        ) : (
          <MessageBubble key={item.message.id} message={item.message} />
        ),
      )}
    </div>
  );
}

/** Pair tool_use calls with their tool_result by toolCallId. */
function pairToolMessages(messages: DisplayMessage[]): { call: DisplayMessage; result?: DisplayMessage }[] {
  const calls = messages.filter((m) => m.toolType === "call");
  const results = messages.filter((m) => m.toolType === "result");

  // Build a lookup of results by toolCallId
  const resultById = new Map<string, DisplayMessage>();
  for (const r of results) {
    if (r.toolCallId) resultById.set(r.toolCallId, r);
  }

  // Match each call to its result by ID, falling back to positional matching
  const usedResults = new Set<string>();
  const pairs = calls.map((call, i) => {
    let result: DisplayMessage | undefined;
    if (call.toolCallId && resultById.has(call.toolCallId)) {
      result = resultById.get(call.toolCallId);
      usedResults.add(call.toolCallId);
    } else if (i < results.length && !usedResults.has(results[i].id)) {
      // Positional fallback for legacy data without IDs
      result = results[i];
      usedResults.add(results[i].id);
    }
    return { call, result };
  });

  // If there are streaming-only messages (just a tool name, no toolType),
  // treat them as calls without results
  const untyped = messages.filter((m) => !m.toolType);
  for (const m of untyped) {
    pairs.push({ call: m, result: undefined });
  }

  return pairs;
}

function ToolCallGroup({ messages }: { messages: DisplayMessage[] }) {
  const [expanded, setExpanded] = useState(false);
  const pairs = pairToolMessages(messages);

  if (pairs.length === 1) {
    return (
      <div className="mx-4 my-0.5">
        <ToolCallCard call={pairs[0].call.content} result={pairs[0].result?.content} />
      </div>
    );
  }

  const label = `${pairs.length} tool calls`;

  return (
    <div className="mx-4 my-0.5 rounded border border-border/50 bg-surface/50 px-3 py-1.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 font-mono text-[11px] text-text-dim transition-colors hover:text-text-muted"
      >
        <span
          className={`inline-block transition-transform ${expanded ? "rotate-90" : ""}`}
        >
          &#9656;
        </span>
        <span className="text-accent/70">{label}</span>
      </button>
      {expanded && (
        <div className="mt-1.5 flex flex-col gap-2 border-t border-border/30 pt-1.5">
          {pairs.map((pair) => (
            <ToolCallCard key={pair.call.id} call={pair.call.content} result={pair.result?.content} />
          ))}
        </div>
      )}
    </div>
  );
}

function ToolCallCard({ call, result }: { call: string; result?: string }) {
  const [open, setOpen] = useState(false);
  const name = extractToolName(call);

  return (
    <div className="rounded border border-border/30 bg-base/50">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center gap-1.5 px-2 py-1 font-mono text-[11px] text-text-dim transition-colors hover:text-text-muted"
      >
        <span className={`inline-block transition-transform ${open ? "rotate-90" : ""}`}>
          &#9656;
        </span>
        <span className="text-accent/60">{name}</span>
      </button>
      {open && (
        <div className="border-t border-border/20">
          <pre className="max-h-32 overflow-y-auto whitespace-pre-wrap break-words px-2 py-1.5 font-mono text-[11px] leading-relaxed text-text-dim">
            {call}
          </pre>
          {result && (
            <>
              <div className="px-2 pt-1.5 text-[9px] font-medium uppercase tracking-wider text-text-dim/40">
                output
              </div>
              <pre className="max-h-48 overflow-y-auto whitespace-pre-wrap break-words rounded-b bg-surface/60 mx-1 mb-1 px-2 py-1.5 font-mono text-[11px] leading-relaxed text-text-dim/60">
                {result}
              </pre>
            </>
          )}
        </div>
      )}
    </div>
  );
}

function extractToolName(content: string): string {
  const match = content.match(/^(\w+)\(/);
  return match ? match[1] : "tool";
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
    return <ThinkingBlock content={message.content} />;
  }

  return (
    <div
      className={`group flex px-4 py-2 ${isUser ? "justify-end" : "justify-start"}`}
    >
      <div
        className={`max-w-[80%] ${
          isUser
            ? "rounded-lg bg-accent-dim px-3 py-2 text-accent whitespace-pre-wrap font-mono text-xs leading-relaxed"
            : "border-l-2 border-accent/30 pl-3 text-text"
        }`}
      >
        {isUser ? (
          <>
            {message.images && message.images.length > 0 && (
              <div className="mb-2 flex flex-wrap gap-2 not-mono">
                {message.images.map((src, i) => (
                  <div key={i} className="overflow-hidden rounded border border-accent/30">
                    <img
                      src={src}
                      alt={`attachment ${i + 1}`}
                      className="block max-h-48 max-w-[300px] object-contain"
                    />
                  </div>
                ))}
                <div className="w-full text-[10px] text-text-dim font-sans">
                  {message.images.length} image{message.images.length > 1 ? "s" : ""} attached
                </div>
              </div>
            )}
            {message.content}
          </>
        ) : (
          <div className="prose-cambium">
            <Markdown remarkPlugins={[remarkGfm]}>{message.content}</Markdown>
          </div>
        )}
        <span className="ml-2 hidden text-[10px] text-text-dim group-hover:inline">
          {new Date(message.timestamp).toLocaleTimeString()}
        </span>
      </div>
    </div>
  );
}

function ThinkingBlock({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mx-4 my-0.5 rounded border border-border/30 bg-surface/30 px-3 py-1.5">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-1.5 text-[10px] font-medium uppercase tracking-wider text-text-dim/60 transition-colors hover:text-text-muted"
      >
        <span className={`inline-block transition-transform ${expanded ? "rotate-90" : ""}`}>
          &#9656;
        </span>
        thinking
      </button>
      {expanded && (
        <div className="mt-1.5 border-t border-border/30 pt-1.5 whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-dim">
          {content}
        </div>
      )}
    </div>
  );
}

