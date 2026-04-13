import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";

export interface TranscriptEntry {
  id: string;
  content: string;
  kind: "text" | "tool_call" | "thinking";
  timestamp: number;
}

type StreamState = "connecting" | "streaming" | "done" | "error";

export function useSessionStream(sessionId: string | null) {
  const [entries, setEntries] = useState<TranscriptEntry[]>([]);
  const [state, setState] = useState<StreamState>("connecting");
  const esRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!sessionId) {
      setEntries([]);
      setState("connecting");
      return;
    }

    const url = `${API_BASE}/sessions/${sessionId}/stream`;
    const es = new EventSource(url);
    esRef.current = es;
    setState("connecting");

    // Track what the previous chunk type was so we know when to start
    // a new entry vs. append to the current one.
    let entryCount = 0;
    let currentContent = "";
    let lastChunkKind: "text" | "tool_call" | "thinking" | null = null;

    function flush(_kind: "text" | "tool_call" | "thinking") {
      // The live-update path already placed an entry with id
      // `entry-${entryCount}` into state for text/thinking chunks. All we
      // need to do here is finalize the accumulator and advance the
      // counter so the next entry gets a fresh id. Appending another
      // entry here would duplicate the message in the transcript.
      if (!currentContent.trim()) return;
      entryCount++;
      currentContent = "";
    }

    es.onopen = () => {
      setState("streaming");
    };

    es.onmessage = (event) => {
      if (event.data === "[DONE]") {
        if (currentContent.trim() && lastChunkKind) {
          flush(lastChunkKind);
        }
        setState("done");
        es.close();
        return;
      }

      try {
        const chunk = JSON.parse(event.data);
        const choice = chunk.choices?.[0];
        if (!choice) return;
        const delta = choice.delta;

        const hasContent = !!delta.content;
        const hasToolCall = !!delta.tool_calls;
        const isThinking = hasContent && choice.thinking;

        if (hasContent) {
          const kind: "text" | "thinking" = isThinking ? "thinking" : "text";

          // If switching from a different kind, flush the previous
          if (lastChunkKind && lastChunkKind !== kind) {
            flush(lastChunkKind);
          }

          currentContent += delta.content;
          lastChunkKind = kind;

          // Live-update: show the current accumulating text entry
          const liveId = `entry-${entryCount}`;
          const liveEntry: TranscriptEntry = {
            id: liveId,
            content: currentContent.trim(),
            kind,
            timestamp: Date.now(),
          };
          setEntries((prev) => {
            const idx = prev.findIndex((e) => e.id === liveId);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = liveEntry;
              return updated;
            }
            return [...prev, liveEntry];
          });
        } else if (hasToolCall) {
          // Flush any accumulated text before the tool call
          if (lastChunkKind && lastChunkKind !== "tool_call") {
            flush(lastChunkKind);
          }

          // Extract tool name for display
          for (const tc of delta.tool_calls) {
            const name = tc.function?.name;
            if (name) {
              const toolId = `entry-${entryCount++}`;
              setEntries((prev) => [
                ...prev,
                {
                  id: toolId,
                  content: name,
                  kind: "tool_call",
                  timestamp: Date.now(),
                },
              ]);
            }
          }
          lastChunkKind = "tool_call";
          currentContent = "";
        }
      } catch {
        // Ignore malformed chunks
      }
    };

    es.onerror = () => {
      // Flush anything remaining
      if (currentContent.trim() && lastChunkKind) {
        flush(lastChunkKind);
      }
      setState("error");
      es.close();
    };

    return () => {
      es.close();
      esRef.current = null;
    };
  }, [sessionId]);

  return { entries, state };
}
