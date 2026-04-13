import { useState, useRef, useEffect, useCallback } from "react";
import { useChatSession } from "../hooks/useChatSession";
import { MessageList } from "./MessageList";
import type { Session } from "../lib/types";
import { Send, Square, X, Image, ChevronDown, ChevronUp, LogOut } from "lucide-react";
import { apiDelete } from "../lib/api";
import { detectCollapsiblePaste, assembleMessage } from "../lib/paste";
import type { CollapsedPaste } from "../lib/paste";

interface Attachment {
  id: string;
  type: "image";
  dataUrl: string;
  name: string;
}

interface ChatViewProps {
  session: Session;
  onEnd?: () => void;
}

export function ChatView({ session, onEnd }: ChatViewProps) {
  const { messages, chatState, sendMessage, cancel } = useChatSession(
    session.id,
  );
  const [input, setInput] = useState("");
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [collapsedPaste, setCollapsedPaste] = useState<CollapsedPaste | null>(
    null,
  );
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll on new messages
  useEffect(() => {
    const el = scrollRef.current;
    if (el) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  // Focus input on mount
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  const addImageFromFile = useCallback((file: File) => {
    if (!file.type.startsWith("image/")) return;
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      setAttachments((prev) => [
        ...prev,
        {
          id: `img-${Date.now()}-${Math.random()}`,
          type: "image",
          dataUrl,
          name: file.name || "pasted image",
        },
      ]);
    };
    reader.readAsDataURL(file);
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => prev.filter((a) => a.id !== id));
  }, []);

  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      const items = e.clipboardData.items;

      // Check for images first
      for (const item of items) {
        if (item.type.startsWith("image/")) {
          e.preventDefault();
          const file = item.getAsFile();
          if (file) addImageFromFile(file);
          return;
        }
      }

      // Check for large text paste
      const text = e.clipboardData.getData("text/plain");
      if (text) {
        const cursorPos = inputRef.current?.selectionStart ?? input.length;
        const collapsed = detectCollapsiblePaste(text, cursorPos);
        if (collapsed) {
          e.preventDefault();
          setCollapsedPaste(collapsed);
          return;
        }
      }
      // Small text pastes fall through to default textarea behavior
    },
    [addImageFromFile],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent) => {
      e.preventDefault();
      for (const file of e.dataTransfer.files) {
        if (file.type.startsWith("image/")) {
          addImageFromFile(file);
        }
      }
    },
    [addImageFromFile],
  );

  const handleSubmit = useCallback(() => {
    const fullMessage = assembleMessage(input, collapsedPaste);

    const hasContent = fullMessage || attachments.length > 0;
    if (!hasContent || chatState === "streaming") return;

    // Build content with image attachments
    const imageDataUrls = attachments
      .filter((a) => a.type === "image")
      .map((a) => a.dataUrl);

    setInput("");
    setAttachments([]);
    setCollapsedPaste(null);

    // Reset textarea height
    if (inputRef.current) {
      inputRef.current.style.height = "auto";
    }

    sendMessage(fullMessage, imageDataUrls.length > 0 ? imageDataUrls : undefined);
  }, [input, collapsedPaste, attachments, chatState, sendMessage]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit();
      }
    },
    [handleSubmit],
  );

  const hasContent =
    input.trim() || collapsedPaste || attachments.length > 0;

  return (
    <div className="flex h-full w-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 border-b border-border px-4 py-2">
        <span className="font-display text-sm text-text-muted">
          {session.routine_name ?? "Chat"}
        </span>
        {chatState === "streaming" && (
          <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-status-active" />
        )}
        <div className="flex-1" />
        <span className="text-[10px] text-text-dim">
          {session.id.slice(0, 8)}
        </span>
        <button
          onClick={async () => {
            try {
              await apiDelete(`/sessions/${session.id}`);
              onEnd?.();
            } catch (e) {
              console.error("Failed to end session:", e);
            }
          }}
          className="flex items-center gap-1 rounded px-2 py-1 text-[11px] text-text-dim transition-colors hover:bg-surface hover:text-status-failed"
          title="End session"
        >
          <LogOut size={12} />
          End
        </button>
      </div>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto py-2">
        {messages.length === 0 && chatState === "idle" && (
          <div className="flex h-full items-center justify-center">
            <span className="text-sm text-text-dim">
              Start the conversation...
            </span>
          </div>
        )}
        <MessageList messages={messages} />
      </div>

      {/* Input area */}
      <div
        className="border-t border-border bg-surface px-4 py-3"
        onDrop={handleDrop}
        onDragOver={(e) => e.preventDefault()}
      >
        {chatState === "error" && (
          <div className="mb-2 rounded border border-status-failed/30 bg-status-failed/10 px-3 py-1.5 text-xs text-status-failed">
            Failed to send message. Try again.
          </div>
        )}

        {/* Collapsed paste preview */}
        {collapsedPaste && (
          <div className="mb-2 rounded border border-border bg-base">
            <div className="flex items-center gap-2 px-3 py-1.5">
              <button
                onClick={() =>
                  setCollapsedPaste((prev) =>
                    prev ? { ...prev, expanded: !prev.expanded } : null,
                  )
                }
                className="flex items-center gap-1 font-mono text-[11px] text-text-dim transition-colors hover:text-text-muted"
              >
                {collapsedPaste.expanded ? (
                  <ChevronUp size={12} />
                ) : (
                  <ChevronDown size={12} />
                )}
                <span>
                  Pasted {collapsedPaste.lineCount} lines (
                  {collapsedPaste.fullText.length.toLocaleString()} chars)
                </span>
              </button>
              <div className="flex-1" />
              <button
                onClick={() => setCollapsedPaste(null)}
                className="text-text-dim transition-colors hover:text-status-failed"
              >
                <X size={12} />
              </button>
            </div>
            {collapsedPaste.expanded ? (
              <pre className="max-h-48 overflow-auto border-t border-border px-3 py-2 font-mono text-[11px] text-text-dim">
                {collapsedPaste.fullText}
              </pre>
            ) : (
              <pre className="border-t border-border px-3 py-1.5 font-mono text-[11px] text-text-dim/60">
                {collapsedPaste.preview}
                {collapsedPaste.lineCount > 4 && "\n..."}
              </pre>
            )}
          </div>
        )}

        {/* Image attachment previews */}
        {attachments.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {attachments.map((att) => (
              <div
                key={att.id}
                className="group relative h-16 w-16 overflow-hidden rounded border border-border"
              >
                <img
                  src={att.dataUrl}
                  alt={att.name}
                  className="h-full w-full object-cover"
                />
                <button
                  onClick={() => removeAttachment(att.id)}
                  className="absolute -right-0.5 -top-0.5 hidden rounded-full bg-base p-0.5 text-text-dim shadow group-hover:block hover:text-status-failed"
                >
                  <X size={10} />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Text input + buttons */}
        <div className="flex items-end gap-2">
          <button
            onClick={() => fileInputRef.current?.click()}
            className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded border border-border text-text-dim transition-colors hover:border-accent hover:text-accent"
            title="Attach image"
          >
            <Image size={16} />
          </button>
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            className="hidden"
            onChange={(e) => {
              for (const file of e.target.files ?? []) {
                addImageFromFile(file);
              }
              e.target.value = "";
            }}
          />
          <textarea
            ref={inputRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            onPaste={handlePaste}
            placeholder={
              collapsedPaste
                ? "Add a message to go with the paste, or just hit Enter..."
                : "Type a message..."
            }
            rows={1}
            className="flex-1 resize-none rounded border border-border bg-base px-3 py-2 font-mono text-sm text-text placeholder:text-text-dim focus:border-accent focus:outline-none"
            style={{
              minHeight: "2.5rem",
              maxHeight: "8rem",
              height: "auto",
              overflow: input.split("\n").length > 1 ? "auto" : "hidden",
            }}
            onInput={(e) => {
              const target = e.target as HTMLTextAreaElement;
              target.style.height = "auto";
              target.style.height = `${Math.min(target.scrollHeight, 128)}px`;
            }}
            disabled={chatState === "streaming"}
          />
          {chatState === "streaming" ? (
            <button
              onClick={cancel}
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded border border-border text-text-dim transition-colors hover:border-status-failed hover:text-status-failed"
              title="Stop"
            >
              <Square size={16} />
            </button>
          ) : (
            <button
              onClick={handleSubmit}
              disabled={!hasContent}
              className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded border border-border text-text-dim transition-colors hover:border-accent hover:text-accent disabled:opacity-30 disabled:hover:border-border disabled:hover:text-text-dim"
              title="Send (Enter)"
            >
              <Send size={16} />
            </button>
          )}
        </div>
        <div className="mt-1 text-[10px] text-text-dim">
          Enter to send · Shift+Enter for newline · Paste or drop images
        </div>
      </div>
    </div>
  );
}
