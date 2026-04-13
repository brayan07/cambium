import { useState, useCallback } from "react";
import { SessionList } from "../components/SessionList";
import { ChatView } from "../components/ChatView";
import { ObservationView } from "../components/ObservationView";
import { SessionHistory } from "../components/SessionHistory";
import { apiPost } from "../lib/api";
import type { Session } from "../lib/types";

/**
 * View state for the main content area.
 *
 * User sessions use ChatView (structured message exchange via REST/SSE).
 * System sessions use ObservationView (read-only SSE stream).
 * Completed sessions use SessionHistory (REST message history).
 */
type ViewState =
  | { mode: "empty" }
  | { mode: "browse"; session: Session }
  | { mode: "chat"; session: Session };

export function ChatPage() {
  const [view, setView] = useState<ViewState>({ mode: "empty" });

  const handleSelectSession = useCallback(
    (session: Session) => {
      // If we're in an active chat, clicking the same session is a no-op
      if (view.mode === "chat" && view.session.id === session.id) return;
      // Clicking a different session while chatting — leave the chat
      setView({ mode: "browse", session });
    },
    [view],
  );

  const handleNewChat = useCallback(async () => {
    try {
      const session = await apiPost<Session>("/sessions", {
        routine_name: "interlocutor",
      });
      setView({ mode: "chat", session });
    } catch (err) {
      console.error("Failed to create session:", err);
    }
  }, []);

  const handleResume = useCallback((session: Session) => {
    setView({ mode: "chat", session });
  }, []);

  const handleEndSession = useCallback(() => {
    setView({ mode: "empty" });
  }, []);

  // --- Derived state ---

  const selectedId =
    view.mode === "empty" ? null : view.session.id;

  // --- Render ---

  const renderMainContent = () => {
    switch (view.mode) {
      case "chat":
        return <ChatView key={view.session.id} session={view.session} onEnd={handleEndSession} />;

      case "browse": {
        const { session } = view;
        // Active system session → observation
        if (session.status === "active" && session.origin === "system") {
          return <ObservationView session={session} />;
        }
        // Active user session (detached) → go straight back to chat
        if (session.status === "active" && session.origin === "user") {
          return <ChatView key={session.id} session={session} />;
        }
        // Completed session → history with resume option
        return (
          <SessionHistory session={session} onResume={handleResume} />
        );
      }

      default:
        return <EmptyState onNewChat={handleNewChat} />;
    }
  };

  return (
    <div className="flex h-full">
      <div className="w-72 flex-shrink-0">
        <SessionList
          selectedId={selectedId}
          onSelect={handleSelectSession}
          onNewChat={handleNewChat}
        />
      </div>
      <div className="flex flex-1 flex-col overflow-hidden">
        {renderMainContent()}
      </div>
    </div>
  );
}

function PausedSession({
  session,
  onResume,
}: {
  session: Session;
  onResume: (session: Session) => void;
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <div className="rounded border border-border bg-surface px-6 py-4">
        <div className="mb-1 font-display text-sm text-text-muted">
          {session.routine_name ?? "Session"} — paused
        </div>
        <p className="mb-4 text-xs text-text-dim">
          This session is waiting for you. Resume to continue the conversation.
        </p>
        <button
          onClick={() => onResume(session)}
          className="rounded border border-accent bg-accent-dim px-4 py-2 font-display text-sm text-accent transition-colors hover:bg-accent hover:text-base"
        >
          Resume
        </button>
      </div>
    </div>
  );
}

function EmptyState({ onNewChat }: { onNewChat: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 text-center">
      <div className="font-display text-lg text-text-dim">
        Select a session or start a new chat
      </div>
      <button
        onClick={onNewChat}
        className="rounded border border-accent bg-accent-dim px-4 py-2 font-display text-sm text-accent transition-colors hover:bg-accent hover:text-base"
      >
        + New Chat
      </button>
    </div>
  );
}
