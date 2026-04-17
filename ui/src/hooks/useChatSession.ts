import { useState, useCallback, useRef, useEffect } from "react";
import { API_BASE } from "../lib/api";
import { fetchAllMessages } from "../lib/messages";
import type { DisplayMessage } from "../components/MessageList";
import { classifyMessages } from "../components/MessageList";

type ChatState = "idle" | "streaming" | "error";

/**
 * Hook for interactive chat sessions.
 *
 * Loads message history on mount, then supports sending messages
 * via POST /sessions/{id}/messages (SSE streaming response).
 */
export function useChatSession(sessionId: string) {
  const [messages, setMessages] = useState<DisplayMessage[]>([]);
  const [chatState, setChatState] = useState<ChatState>("idle");
  const abortRef = useRef<AbortController | null>(null);
  const messageCountRef = useRef(0);

  // Load existing message history on mount
  useEffect(() => {
    let cancelled = false;
    fetchAllMessages(sessionId).then((raw) => {
      if (cancelled) return;
      const classified = classifyMessages(raw);
      setMessages(classified);
      messageCountRef.current = classified.length;
    });
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const sendMessage = useCallback(
    async (content: string, imageDataUrls?: string[]) => {
      if (chatState === "streaming") return;

      // Add user message to display immediately
      const userMsg: DisplayMessage = {
        id: `user-${Date.now()}`,
        content,
        role: "user",
        timestamp: Date.now(),
        images: imageDataUrls,
      };
      setMessages((prev) => [...prev, userMsg]);
      setChatState("streaming");

      // Streaming state for the assistant's response
      let assistantContent = "";
      let assistantId = `assistant-${Date.now()}`;
      let currentKind: "text" | "thinking" | null = null;

      const abort = new AbortController();
      abortRef.current = abort;

      try {
        const body: Record<string, unknown> = {
          messages: [{ role: "user", content }],
          stream: true,
        };
        if (imageDataUrls && imageDataUrls.length > 0) {
          body.images = imageDataUrls;
        }

        const res = await fetch(`${API_BASE}/sessions/${sessionId}/messages`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
          signal: abort.signal,
        });

        if (!res.ok) {
          throw new Error(`Send failed: ${res.status}`);
        }

        const reader = res.body?.getReader();
        if (!reader) throw new Error("No response body");

        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });
          const lines = buffer.split("\n");
          buffer = lines.pop() ?? "";

          for (const line of lines) {
            if (!line.startsWith("data: ")) continue;
            const data = line.slice(6).trim();

            if (data === "[DONE]") {
              continue;
            }

            try {
              const chunk = JSON.parse(data);
              const choice = chunk.choices?.[0];
              if (!choice) continue;
              const delta = choice.delta;

              if (!delta.content) continue;

              const blockMarker: string | undefined = choice.block_marker;
              const isThinking = !!choice.thinking;

              // Discrete block (tool_use / tool_result / thinking):
              // flush accumulated text, then add as its own message.
              if (blockMarker) {
                if (assistantContent.trim() && currentKind) {
                  const role = currentKind === "thinking" ? "thinking" as const : "assistant" as const;
                  const flushedId = assistantId;
                  setMessages((prev) => {
                    const filtered = prev.filter((m) => m.id !== flushedId);
                    return [
                      ...filtered,
                      { id: flushedId, content: assistantContent.trim(), role, timestamp: Date.now() },
                    ];
                  });
                  assistantContent = "";
                  assistantId = `assistant-${Date.now()}`;
                  currentKind = null;
                }

                // Classify the block via classifyMessages for proper
                // toolType / toolCallId extraction.
                const classified = classifyMessages([{
                  id: `block-${Date.now()}-${Math.random()}`,
                  content: delta.content,
                  role: "assistant",
                  created_at: new Date().toISOString(),
                }]);
                if (classified.length > 0) {
                  setMessages((prev) => [...prev, ...classified]);
                }
                continue;
              }

              // Streaming text delta: accumulate.
              const kind = isThinking ? "thinking" : "text";
              if (currentKind && currentKind !== kind && assistantContent.trim()) {
                const role = currentKind === "thinking" ? "thinking" as const : "assistant" as const;
                const flushedId = assistantId;
                setMessages((prev) => {
                  const filtered = prev.filter((m) => m.id !== flushedId);
                  return [
                    ...filtered,
                    { id: flushedId, content: assistantContent.trim(), role, timestamp: Date.now() },
                  ];
                });
                assistantContent = "";
                assistantId = `assistant-${Date.now()}`;
              }

              currentKind = kind;
              assistantContent += delta.content;

              const role = isThinking ? "thinking" as const : "assistant" as const;
              const liveMsg: DisplayMessage = {
                id: assistantId,
                content: assistantContent.trim(),
                role,
                timestamp: Date.now(),
              };
              setMessages((prev) => {
                const idx = prev.findIndex((m) => m.id === assistantId);
                if (idx >= 0) {
                  const updated = [...prev];
                  updated[idx] = liveMsg;
                  return updated;
                }
                return [...prev, liveMsg];
              });
            } catch {
              // Ignore malformed chunks
            }
          }
        }

        // Stream finished — reload full history from REST API.
        // Streaming only carries partial data (tool names without args/results).
        // Small delay ensures backend has finished persisting all messages.
        await new Promise((r) => setTimeout(r, 300));
        try {
          const raw = await fetchAllMessages(sessionId);
          const classified = classifyMessages(raw);
          setMessages(classified);
          messageCountRef.current = classified.length;
        } catch {
          // Keep streaming messages as-is on failure
        }

        setChatState("idle");
      } catch (err) {
        if ((err as Error).name !== "AbortError") {
          setChatState("error");
        }
      } finally {
        abortRef.current = null;
      }
    },
    [sessionId, chatState],
  );

  const cancel = useCallback(() => {
    abortRef.current?.abort();
    setChatState("idle");
  }, []);

  return { messages, chatState, sendMessage, cancel };
}
