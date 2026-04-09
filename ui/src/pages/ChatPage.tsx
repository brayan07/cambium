import { useState, useCallback } from "react";
import { SessionList } from "../components/SessionList";
import { Terminal } from "../components/Terminal";
import { ObservationView } from "../components/ObservationView";
import { SessionHistory } from "../components/SessionHistory";
import type { Session } from "../lib/types";

export function ChatPage() {
  const [selectedSession, setSelectedSession] = useState<Session | null>(null);
  const [terminalSession, setTerminalSession] = useState<{
    wsPath: string;
    sessionId: string;
  } | null>(null);

  const handleNewChat = useCallback(() => {
    const wsPath = "/terminal/new?routine=interlocutor";
    const tempId = `new-${Date.now()}`;
    setTerminalSession({ wsPath, sessionId: tempId });
    setSelectedSession(null);
  }, []);

  const handleSelectSession = useCallback((session: Session) => {
    setSelectedSession(session);

    if (session.origin === "user" && session.status === "active") {
      // Active user session → terminal (attach)
      setTerminalSession({
        wsPath: `/terminal/${session.id}`,
        sessionId: session.id,
      });
    } else {
      // Everything else: clear terminal, show appropriate view
      setTerminalSession(null);
    }
  }, []);

  const handleResume = useCallback((session: Session) => {
    setTerminalSession({
      wsPath: `/terminal/${session.id}`,
      sessionId: session.id,
    });
  }, []);

  const handleSessionEnd = useCallback(() => {
    setTerminalSession(null);
  }, []);

  const renderMainContent = () => {
    // Terminal is active (new chat, attached session, or resumed session)
    if (terminalSession) {
      return (
        <Terminal
          key={terminalSession.sessionId}
          wsPath={terminalSession.wsPath}
          onSessionEnd={handleSessionEnd}
        />
      );
    }

    if (selectedSession) {
      // Active system session → observation
      if (
        selectedSession.status === "active" &&
        selectedSession.origin === "system"
      ) {
        return <ObservationView session={selectedSession} />;
      }

      // Any completed/failed session → history view with resume option
      return (
        <SessionHistory session={selectedSession} onResume={handleResume} />
      );
    }

    return <EmptyState onNewChat={handleNewChat} />;
  };

  return (
    <div className="flex h-full">
      <div className="w-72 flex-shrink-0">
        <SessionList
          selectedId={selectedSession?.id ?? null}
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
