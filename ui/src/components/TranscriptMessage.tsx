import { useState } from "react";
import type { TranscriptEntry } from "../hooks/useSessionStream";

interface TranscriptMessageProps {
  entry: TranscriptEntry;
}

export function TranscriptMessage({ entry }: TranscriptMessageProps) {
  if (entry.kind === "thinking") {
    return (
      <div className="px-4 py-1">
        <div className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-text-dim italic">
          {entry.content}
        </div>
      </div>
    );
  }

  // Regular text content
  return (
    <div className="group px-4 py-2">
      <div className="whitespace-pre-wrap font-mono text-xs leading-relaxed text-text">
        {entry.content}
      </div>
      <span className="mt-0.5 hidden text-[10px] text-text-dim group-hover:block">
        {new Date(entry.timestamp).toLocaleTimeString()}
      </span>
    </div>
  );
}

/** A collapsible group of consecutive tool calls. Collapsed by default. */
export function ToolCallGroup({ entries }: { entries: TranscriptEntry[] }) {
  const [expanded, setExpanded] = useState(false);

  if (entries.length === 0) return null;

  const label =
    entries.length === 1
      ? entries[0].content
      : `${entries.length} tool calls`;

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
          {entries.map((e) => (
            <div key={e.id} className="font-mono text-[11px] text-text-dim py-px">
              {e.content}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
