import { useEffect, useRef, useState } from "react";
import "@xterm/xterm/css/xterm.css";
import {
  useTerminalContext,
  type ConnectionState,
  type TerminalSession,
} from "../contexts/TerminalContext";

interface TerminalProps {
  wsPath: string;
  onSessionEnd?: () => void;
  onSessionId?: (sessionId: string) => void;
}

export function Terminal({ wsPath, onSessionEnd, onSessionId }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const sessionRef = useRef<TerminalSession | null>(null);
  const onSessionEndRef = useRef(onSessionEnd);
  onSessionEndRef.current = onSessionEnd;
  const onSessionIdRef = useRef(onSessionId);
  onSessionIdRef.current = onSessionId;
  const [state, setState] = useState<ConnectionState>("connecting");
  const ctx = useTerminalContext();

  useEffect(() => {
    if (!containerRef.current) return;

    const session = ctx.getOrCreate(wsPath, {
      onSessionId: (id) => onSessionIdRef.current?.(id),
      onSessionEnd: () => onSessionEndRef.current?.(),
      onStateChange: setState,
    });
    sessionRef.current = session;

    setState(session.state);

    // Adopt the context-owned DOM element into our container
    containerRef.current.appendChild(session.containerEl);

    // Set up resize handling for this mount
    const observer = new ResizeObserver(() => {
      session.fitAddon.fit();
      if (session.ws.readyState === WebSocket.OPEN) {
        const dims = session.fitAddon.proposeDimensions();
        if (dims) {
          session.ws.send(
            JSON.stringify({ type: "resize", rows: dims.rows, cols: dims.cols }),
          );
        }
      }
    });
    observer.observe(containerRef.current);
    session.resizeObserver = observer;

    // Refit after attach in case container size changed
    requestAnimationFrame(() => {
      session.fitAddon.fit();
      session.term.focus();
    });

    return () => {
      observer.disconnect();
      session.resizeObserver = null;
      // Detach the terminal element but don't destroy it
      if (session.containerEl.parentNode) {
        session.containerEl.parentNode.removeChild(session.containerEl);
      }
    };
  }, [wsPath, ctx]);

  return (
    <div className="relative flex h-full w-full flex-col">
      {state === "connecting" && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-base/80">
          <div className="flex items-center gap-2 font-display text-sm text-accent">
            <span className="inline-block h-2 w-2 animate-pulse rounded-full bg-accent" />
            Connecting...
          </div>
        </div>
      )}
      {state === "disconnected" && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-base/80">
          <div className="text-center">
            <div className="font-display text-sm text-text-muted">
              Session ended
            </div>
          </div>
        </div>
      )}
      {state === "error" && (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-base/80">
          <div className="text-center">
            <div className="font-display text-sm text-status-failed">
              Connection failed
            </div>
            <p className="mt-1 text-xs text-text-dim">
              Is the Cambium server running?
            </p>
          </div>
        </div>
      )}

      <div ref={containerRef} className="flex-1 p-1" />
    </div>
  );
}
