import { useMemo } from "react";
import { useSessions } from "../hooks/useSessions";
import { StatusBadge } from "./StatusBadge";
import type { Session } from "../lib/types";
import { Plus } from "lucide-react";

interface SessionListProps {
  selectedId: string | null;
  onSelect: (session: Session) => void;
  onNewChat: () => void;
}

function timeAgo(iso: string): string {
  const seconds = Math.floor(
    (Date.now() - new Date(iso).getTime()) / 1000,
  );
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function sessionLabel(s: Session): string {
  if (s.metadata?.title && typeof s.metadata.title === "string") {
    return s.metadata.title;
  }
  return s.routine_name ?? "Session";
}

export function SessionList({
  selectedId,
  onSelect,
  onNewChat,
}: SessionListProps) {
  const { data, isLoading } = useSessions({ limit: 50 });
  const sessions = data ?? [];

  const grouped = useMemo(() => {
    const active: Session[] = [];
    const userHistory: Session[] = [];
    const systemHistory: Session[] = [];

    for (const s of sessions) {
      if (s.status === "active") {
        active.push(s);
      } else if (s.origin === "user") {
        userHistory.push(s);
      } else {
        systemHistory.push(s);
      }
    }

    return { active, userHistory, systemHistory };
  }, [sessions]);

  return (
    <div className="flex h-full flex-col border-r border-border bg-surface">
      {/* Header */}
      <div className="flex h-12 items-center justify-between border-b border-border px-3">
        <span className="font-display text-xs font-medium uppercase tracking-wider text-text-muted">
          Sessions
        </span>
        <button
          onClick={onNewChat}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs text-accent transition-colors hover:bg-accent-dim"
        >
          <Plus size={14} />
          <span>New</span>
        </button>
      </div>

      {/* Session groups */}
      <div className="flex-1 overflow-y-auto px-2 py-2">
        {isLoading && (
          <p className="px-2 py-4 text-center text-xs text-text-dim">
            Loading sessions...
          </p>
        )}

        {!isLoading && sessions.length === 0 && (
          <p className="px-2 py-4 text-center text-xs text-text-dim">
            No sessions yet. Start a new chat.
          </p>
        )}

        <SessionGroup
          label="Active"
          sessions={grouped.active}
          selectedId={selectedId}
          onSelect={onSelect}
        />
        <SessionGroup
          label="Your Conversations"
          sessions={grouped.userHistory}
          selectedId={selectedId}
          onSelect={onSelect}
        />
        <SessionGroup
          label="System"
          sessions={grouped.systemHistory}
          selectedId={selectedId}
          onSelect={onSelect}
          defaultCollapsed
        />
      </div>
    </div>
  );
}

function SessionGroup({
  label,
  sessions,
  selectedId,
  onSelect,
  defaultCollapsed = false,
}: {
  label: string;
  sessions: Session[];
  selectedId: string | null;
  onSelect: (s: Session) => void;
  defaultCollapsed?: boolean;
}) {
  if (sessions.length === 0) return null;

  return (
    <div className="mb-3">
      <div className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-widest text-text-dim">
        {label}
      </div>
      <div className="flex flex-col gap-0.5">
        {(defaultCollapsed ? sessions.slice(0, 5) : sessions).map((s) => (
          <button
            key={s.id}
            onClick={() => onSelect(s)}
            className={`flex w-full flex-col gap-0.5 rounded px-2 py-1.5 text-left transition-colors ${
              selectedId === s.id
                ? "bg-accent-dim border-l-2 border-accent"
                : "border-l-2 border-transparent hover:bg-surface-raised"
            }`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="truncate text-xs font-medium text-text">
                {sessionLabel(s)}
              </span>
              <StatusBadge status={s.status} />
            </div>
            <span className="text-[10px] text-text-dim">
              {s.routine_name} &middot; {timeAgo(s.updated_at)}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
