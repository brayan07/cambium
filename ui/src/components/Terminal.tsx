import { useEffect, useRef, useState } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { AttachAddon } from "@xterm/addon-attach";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";
import { terminalWsUrl } from "../lib/api";

interface TerminalProps {
  /** WebSocket path (e.g., "/terminal/new?routine=interlocutor") */
  wsPath: string;
  /** Called when the terminal session ends (WebSocket closes) */
  onSessionEnd?: () => void;
}

type ConnectionState = "connecting" | "connected" | "disconnected" | "error";

const THEME = {
  background: "#0a0a0f",
  foreground: "#e0e0e8",
  cursor: "#d4a843",
  cursorAccent: "#0a0a0f",
  selectionBackground: "#d4a84366",
  selectionForeground: "#e0e0e8",
  black: "#0a0a0f",
  red: "#ef4444",
  green: "#4ade80",
  yellow: "#d4a843",
  blue: "#60a5fa",
  magenta: "#c084fc",
  cyan: "#22d3ee",
  white: "#e0e0e8",
  brightBlack: "#555570",
  brightRed: "#f87171",
  brightGreen: "#86efac",
  brightYellow: "#e0b850",
  brightBlue: "#93c5fd",
  brightMagenta: "#d8b4fe",
  brightCyan: "#67e8f9",
  brightWhite: "#ffffff",
};

export function Terminal({ wsPath, onSessionEnd }: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const onSessionEndRef = useRef(onSessionEnd);
  onSessionEndRef.current = onSessionEnd;
  const [state, setState] = useState<ConnectionState>("connecting");

  useEffect(() => {
    if (!containerRef.current) return;

    // Create terminal
    const term = new XTerm({
      theme: THEME,
      fontFamily: "'JetBrains Mono', monospace",
      fontSize: 13,
      lineHeight: 1.4,
      cursorBlink: true,
      cursorStyle: "bar",
      scrollback: 10000,
      allowProposedApi: true,
    });
    termRef.current = term;

    // Addons
    const fitAddon = new FitAddon();
    fitRef.current = fitAddon;
    term.loadAddon(fitAddon);
    term.loadAddon(new WebLinksAddon());

    // Mount
    term.open(containerRef.current);
    fitAddon.fit();

    // Connect WebSocket
    const url = terminalWsUrl(wsPath);
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.binaryType = "arraybuffer";

    ws.onopen = () => {
      setState("connected");
      const attachAddon = new AttachAddon(ws);
      term.loadAddon(attachAddon);

      // Send initial resize
      const dims = fitAddon.proposeDimensions();
      if (dims) {
        ws.send(
          JSON.stringify({ type: "resize", rows: dims.rows, cols: dims.cols }),
        );
      }

      term.focus();
    };

    ws.onclose = () => {
      setState("disconnected");
      onSessionEndRef.current?.();
    };

    ws.onerror = () => {
      setState("error");
    };

    // Handle container resize
    const observer = new ResizeObserver(() => {
      fitAddon.fit();
      if (ws.readyState === WebSocket.OPEN) {
        const dims = fitAddon.proposeDimensions();
        if (dims) {
          ws.send(
            JSON.stringify({
              type: "resize",
              rows: dims.rows,
              cols: dims.cols,
            }),
          );
        }
      }
    });
    observer.observe(containerRef.current);

    // Keepalive ping every 60s
    const keepalive = setInterval(() => {
      if (ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "keepalive" }));
      }
    }, 60_000);

    return () => {
      clearInterval(keepalive);
      observer.disconnect();
      ws.close();
      term.dispose();
      termRef.current = null;
      wsRef.current = null;
      fitRef.current = null;
    };
  }, [wsPath]);

  return (
    <div className="relative flex h-full w-full flex-col">
      {/* Connection status overlay */}
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

      {/* Terminal container */}
      <div ref={containerRef} className="flex-1 p-1" />
    </div>
  );
}
