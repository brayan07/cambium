import {
  createContext,
  useContext,
  useCallback,
  useRef,
  type ReactNode,
} from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { AttachAddon } from "@xterm/addon-attach";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { terminalWsUrl } from "../lib/api";

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

export type ConnectionState = "connecting" | "connected" | "disconnected" | "error";

export interface TerminalSession {
  term: XTerm;
  ws: WebSocket;
  fitAddon: FitAddon;
  containerEl: HTMLDivElement;
  state: ConnectionState;
  keepaliveId: ReturnType<typeof setInterval>;
  resizeObserver: ResizeObserver | null;
}

interface TerminalContextValue {
  getOrCreate: (
    wsPath: string,
    callbacks?: {
      onSessionId?: (id: string) => void;
      onSessionEnd?: () => void;
      onStateChange?: (state: ConnectionState) => void;
    },
  ) => TerminalSession;
  destroy: (wsPath: string) => void;
  get: (wsPath: string) => TerminalSession | undefined;
}

const TerminalCtx = createContext<TerminalContextValue | null>(null);

export function useTerminalContext(): TerminalContextValue {
  const ctx = useContext(TerminalCtx);
  if (!ctx) throw new Error("useTerminalContext must be inside TerminalProvider");
  return ctx;
}

export function TerminalProvider({ children }: { children: ReactNode }) {
  const sessions = useRef(new Map<string, TerminalSession>());

  const destroy = useCallback((wsPath: string) => {
    const entry = sessions.current.get(wsPath);
    if (!entry) return;
    clearInterval(entry.keepaliveId);
    entry.resizeObserver?.disconnect();
    entry.ws.close();
    entry.term.dispose();
    sessions.current.delete(wsPath);
  }, []);

  const get = useCallback((wsPath: string) => {
    return sessions.current.get(wsPath);
  }, []);

  const getOrCreate = useCallback(
    (
      wsPath: string,
      callbacks?: {
        onSessionId?: (id: string) => void;
        onSessionEnd?: () => void;
        onStateChange?: (state: ConnectionState) => void;
      },
    ): TerminalSession => {
      const existing = sessions.current.get(wsPath);
      if (existing) return existing;

      const containerEl = document.createElement("div");
      containerEl.style.width = "100%";
      containerEl.style.height = "100%";

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

      const fitAddon = new FitAddon();
      term.loadAddon(fitAddon);
      term.loadAddon(new WebLinksAddon());

      term.open(containerEl);

      const url = terminalWsUrl(wsPath);
      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";

      const entry: TerminalSession = {
        term,
        ws,
        fitAddon,
        containerEl,
        state: "connecting",
        keepaliveId: 0 as unknown as ReturnType<typeof setInterval>,
        resizeObserver: null,
      };

      const setState = (s: ConnectionState) => {
        entry.state = s;
        callbacks?.onStateChange?.(s);
      };

      ws.onopen = () => {
        setState("connected");

        const earlyHandler = (ev: MessageEvent) => {
          if (typeof ev.data === "string") {
            try {
              const ctrl = JSON.parse(ev.data);
              if (ctrl.type === "session_init" && ctrl.session_id) {
                callbacks?.onSessionId?.(ctrl.session_id);
              }
            } catch {
              term.write(ev.data);
            }
            return;
          }
          ws.removeEventListener("message", earlyHandler);
          const attachAddon = new AttachAddon(ws);
          term.loadAddon(attachAddon);
          term.write(new Uint8Array(ev.data));
        };
        ws.addEventListener("message", earlyHandler);

        setTimeout(() => {
          ws.removeEventListener("message", earlyHandler);
          if (term.buffer.normal.length <= 1) {
            const attachAddon = new AttachAddon(ws);
            term.loadAddon(attachAddon);
          }
        }, 2000);

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
        callbacks?.onSessionEnd?.();
      };

      ws.onerror = () => {
        setState("error");
      };

      entry.keepaliveId = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: "keepalive" }));
        }
      }, 60_000);

      sessions.current.set(wsPath, entry);
      return entry;
    },
    [],
  );

  const value: TerminalContextValue = { getOrCreate, destroy, get };

  return <TerminalCtx.Provider value={value}>{children}</TerminalCtx.Provider>;
}
