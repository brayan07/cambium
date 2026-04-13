import { useEffect, useRef, useState } from "react";
import { API_BASE } from "../lib/api";

/**
 * A streamed transcript entry. ``kind`` maps 1:1 onto the adapter's
 * chunk ``block_marker``: text chunks without a marker accumulate into
 * a single text entry; chunks carrying a marker (``tool_use``,
 * ``tool_result``, ``thinking``) each become their own standalone
 * entry so the downstream renderer can treat them as discrete blocks.
 */
export interface TranscriptEntry {
  id: string;
  content: string;
  kind: "text" | "thinking" | "tool_use" | "tool_result";
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

    // Rolling state for streaming text accumulation. Markered chunks
    // bypass accumulation and push their own entry each time.
    let entryCount = 0;
    let textBuf = "";

    function flushText() {
      if (!textBuf.trim()) {
        textBuf = "";
        return;
      }
      entryCount++;
      textBuf = "";
    }

    es.onopen = () => {
      setState("streaming");
    };

    es.onmessage = (event) => {
      if (event.data === "[DONE]") {
        flushText();
        setState("done");
        es.close();
        return;
      }

      try {
        const chunk = JSON.parse(event.data);
        const choice = chunk.choices?.[0];
        if (!choice) return;
        const delta = choice.delta ?? {};
        const content: string | undefined = delta.content;
        const blockMarker: string | undefined = choice.block_marker;

        if (typeof content !== "string" || content.length === 0) {
          return;
        }

        // Discrete block (tool_use / tool_result / thinking): flush any
        // pending text first, then append this block as its own entry.
        if (blockMarker) {
          flushText();
          const kind =
            blockMarker === "tool_use"
              ? "tool_use"
              : blockMarker === "tool_result"
                ? "tool_result"
                : "thinking";
          const id = `entry-${entryCount++}`;
          setEntries((prev) => [
            ...prev,
            { id, content, kind, timestamp: Date.now() },
          ]);
          return;
        }

        // Streaming text delta: accumulate into the current text entry.
        textBuf += content;
        const liveId = `entry-${entryCount}`;
        const liveEntry: TranscriptEntry = {
          id: liveId,
          content: textBuf.trim(),
          kind: "text",
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
      } catch {
        // Ignore malformed chunks
      }
    };

    es.onerror = () => {
      flushText();
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
