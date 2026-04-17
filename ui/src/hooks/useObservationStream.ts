import { useEffect, useRef, useState, useCallback } from "react";
import { API_BASE, apiGet } from "../lib/api";
import type { DisplayMessage } from "../components/MessageList";
import { classifyMessages } from "../components/MessageList";

export type ConnectionMode = "connecting" | "streaming" | "polling" | "done";

interface RawMessage {
  id: string;
  content: string;
  role: string;
  created_at: string;
}

const POLL_INTERVAL_MS = 3000;
const SSE_RETRY_INTERVAL_MS = 30000;

export function useObservationStream(sessionId: string | null) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [mode, setMode] = useState<ConnectionMode>("connecting");
  const [sseAttempt, setSseAttempt] = useState(0);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const poll = useCallback(async () => {
    if (!sessionId) return;
    try {
      const raw = await apiGet<RawMessage[]>(
        `/sessions/${sessionId}/messages`,
      );
      setMessages(classifyMessages(raw));
    } catch {
      // keep existing messages
    }
  }, [sessionId]);

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    setMode("polling");
    poll();
    pollRef.current = setInterval(poll, POLL_INTERVAL_MS);
  }, [poll]);

  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      setMode("connecting");
      return;
    }

    const es = new EventSource(`${API_BASE}/sessions/${sessionId}/stream`);

    let entryCount = 0;
    let currentContent = "";
    let lastChunkKind: "text" | "tool_call" | "thinking" | null = null;

    function flush() {
      if (!currentContent.trim()) return;
      entryCount++;
      currentContent = "";
    }

    es.onopen = () => {
      stopPolling();
      setMode("streaming");
      if (retryRef.current) {
        clearTimeout(retryRef.current);
        retryRef.current = null;
      }
    };

    es.onmessage = (event) => {
      if (event.data === "[DONE]") {
        if (currentContent.trim() && lastChunkKind) flush();
        setMode("done");
        es.close();
        poll();
        return;
      }

      try {
        const chunk = JSON.parse(event.data);
        const choice = chunk.choices?.[0];
        if (!choice) return;
        const delta = choice.delta;

        if (delta.content) {
          const kind: "text" | "thinking" = choice.thinking
            ? "thinking"
            : "text";
          if (lastChunkKind && lastChunkKind !== kind) flush();
          currentContent += delta.content;
          lastChunkKind = kind;

          const liveId = `entry-${entryCount}`;
          const liveMsg: DisplayMessage = {
            id: liveId,
            content: currentContent.trim(),
            role: kind === "thinking" ? "thinking" : "assistant",
            timestamp: Date.now(),
          };
          setMessages((prev) => {
            const idx = prev.findIndex((e) => e.id === liveId);
            if (idx >= 0) {
              const updated = [...prev];
              updated[idx] = liveMsg;
              return updated;
            }
            return [...prev, liveMsg];
          });
        } else if (delta.tool_calls) {
          if (lastChunkKind && lastChunkKind !== "tool_call") flush();

          for (const tc of delta.tool_calls) {
            const name = tc.function?.name;
            if (name) {
              const toolId = `entry-${entryCount++}`;
              setMessages((prev) => [
                ...prev,
                {
                  id: toolId,
                  content: name,
                  role: "tool" as const,
                  toolType: "call" as const,
                  toolCallId: tc.id,
                  timestamp: Date.now(),
                },
              ]);
            }
          }
          lastChunkKind = "tool_call";
          currentContent = "";
        }
      } catch {
        // ignore malformed chunks
      }
    };

    es.onerror = () => {
      if (currentContent.trim() && lastChunkKind) flush();
      es.close();
      startPolling();
      retryRef.current = setTimeout(() => {
        setSseAttempt((n) => n + 1);
      }, SSE_RETRY_INTERVAL_MS);
    };

    return () => {
      es.close();
      if (retryRef.current) {
        clearTimeout(retryRef.current);
        retryRef.current = null;
      }
    };
  }, [sessionId, sseAttempt, stopPolling, startPolling, poll]);

  useEffect(() => {
    return stopPolling;
  }, [stopPolling]);

  return { messages, mode };
}
