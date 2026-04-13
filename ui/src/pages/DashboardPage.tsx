import { useMemo, useState } from "react";
import { Link } from "react-router";
import {
  Activity,
  Inbox,
  ListTodo,
  Radio,
  AlertTriangle,
  CircleDot,
} from "lucide-react";
import { useHealth } from "../hooks/useHealth";
import { useSessions } from "../hooks/useSessions";
import { useRequestSummary } from "../hooks/useRequests";
import { useWorkItems } from "../hooks/useWorkItems";
import { useQueueStatus, useRecentEvents } from "../hooks/useDashboard";
import type { ChannelEvent, Session, WorkItemStatus } from "../lib/types";

export function DashboardPage() {
  const health = useHealth();
  const queue = useQueueStatus();
  const activeSessions = useSessions({ status: "active" });
  const requestSummary = useRequestSummary();
  const workItems = useWorkItems();
  const events = useRecentEvents(50);

  const workCounts = useMemo(() => {
    const counts: Partial<Record<WorkItemStatus, number>> = {};
    if (workItems.data) {
      for (const item of workItems.data.items) {
        counts[item.status] = (counts[item.status] ?? 0) + 1;
      }
    }
    return counts;
  }, [workItems.data]);

  const pendingRequestCount = useMemo(() => {
    const counts = requestSummary.data?.counts ?? {};
    let total = 0;
    for (const type of Object.keys(counts)) {
      total += counts[type]?.pending ?? 0;
    }
    return total;
  }, [requestSummary.data]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-4 border-b border-border px-6 py-3">
        <h1 className="font-display text-sm font-semibold text-text">
          Dashboard
        </h1>
        <span className="text-[10px] uppercase tracking-wide text-text-dim">
          System overview
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-6">
        {/* Summary cards */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <SummaryCard
            icon={<Activity className="h-4 w-4" />}
            label="Sessions"
            primary={activeSessions.data?.length ?? 0}
            primaryLabel="active"
            footer={
              health.data
                ? health.data.consumer_running
                  ? "consumer running"
                  : "consumer stopped"
                : "—"
            }
            footerTone={
              health.data?.consumer_running ? "good" : "bad"
            }
          />
          <SummaryCard
            icon={<Radio className="h-4 w-4" />}
            label="Queue"
            primary={health.data?.pending_messages ?? 0}
            primaryLabel="pending"
            footer={
              health.data
                ? `${health.data.in_flight_messages} in flight · ${queue.data?.subscribed_channels.length ?? 0} channels`
                : "—"
            }
          />
          <SummaryCard
            icon={<Inbox className="h-4 w-4" />}
            label="Requests"
            primary={pendingRequestCount}
            primaryLabel="pending"
            footer={
              <Link
                to="/inbox"
                className="text-accent hover:text-accent-hover"
              >
                open inbox →
              </Link>
            }
          />
          <SummaryCard
            icon={<ListTodo className="h-4 w-4" />}
            label="Work Items"
            primary={workCounts.active ?? 0}
            primaryLabel="active"
            footer={
              <span>
                <span className="text-status-failed">
                  {workCounts.blocked ?? 0}
                </span>{" "}
                blocked ·{" "}
                <span className="text-status-completed">
                  {workCounts.completed ?? 0}
                </span>{" "}
                done
              </span>
            }
          />
        </div>

        {/* Two-column: active sessions + recent activity */}
        <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-2">
          <Panel title="Active Sessions">
            {activeSessions.isLoading && <Empty>Loading...</Empty>}
            {!activeSessions.isLoading &&
              (activeSessions.data?.length ?? 0) === 0 && (
                <Empty>No active sessions.</Empty>
              )}
            <ul className="divide-y divide-border">
              {activeSessions.data?.map((s) => (
                <SessionRow key={s.id} session={s} />
              ))}
            </ul>
          </Panel>

          <Panel title="Recent Activity">
            {events.isLoading && <Empty>Loading...</Empty>}
            {!events.isLoading && (events.data?.length ?? 0) === 0 && (
              <Empty>No recent events.</Empty>
            )}
            <ul className="divide-y divide-border">
              {events.data?.slice(0, 20).map((ev) => (
                <EventRow key={ev.id} event={ev} />
              ))}
            </ul>
          </Panel>
        </div>

        {!health.data?.consumer_running && health.data && (
          <div className="mt-6 flex items-center gap-2 rounded border border-status-failed/40 bg-status-failed/10 px-4 py-3 text-sm text-status-failed">
            <AlertTriangle className="h-4 w-4" />
            <span>
              Consumer is not running. Queued messages will not be processed.
            </span>
          </div>
        )}
      </div>
    </div>
  );
}

// --- subcomponents ---

interface SummaryCardProps {
  icon: React.ReactNode;
  label: string;
  primary: number;
  primaryLabel: string;
  footer: React.ReactNode;
  footerTone?: "good" | "bad" | "neutral";
}

function SummaryCard({
  icon,
  label,
  primary,
  primaryLabel,
  footer,
  footerTone = "neutral",
}: SummaryCardProps) {
  const footerColor =
    footerTone === "good"
      ? "text-status-active"
      : footerTone === "bad"
        ? "text-status-failed"
        : "text-text-dim";
  return (
    <div className="rounded border border-border bg-surface p-4">
      <div className="flex items-center gap-2 text-text-muted">
        {icon}
        <span className="text-[10px] uppercase tracking-wide">{label}</span>
      </div>
      <div className="mt-3 flex items-baseline gap-2">
        <span className="font-display text-3xl font-semibold text-text">
          {primary}
        </span>
        <span className="text-[10px] uppercase tracking-wide text-text-dim">
          {primaryLabel}
        </span>
      </div>
      <div className={`mt-2 text-[11px] ${footerColor}`}>{footer}</div>
    </div>
  );
}

function Panel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded border border-border bg-surface">
      <div className="border-b border-border px-4 py-2">
        <h2 className="font-display text-xs font-semibold uppercase tracking-wide text-text">
          {title}
        </h2>
      </div>
      <div className="max-h-96 overflow-y-auto">{children}</div>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-6 text-center text-xs text-text-dim">{children}</div>
  );
}

function EventRow({ event }: { event: ChannelEvent }) {
  const [open, setOpen] = useState(false);
  return (
    <li className="text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-start gap-3 px-3 py-2 text-left hover:bg-surface-raised"
      >
        <CircleDot className="mt-0.5 h-3 w-3 flex-shrink-0 text-text-dim" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <span className="font-mono text-text">{event.channel}</span>
            <span className="text-text-dim">
              {formatTimestamp(event.timestamp)}
            </span>
            {event.source_session_id && (
              <span className="truncate font-mono text-[10px] text-text-dim">
                · {event.source_session_id.slice(0, 8)}
              </span>
            )}
          </div>
          <div className="truncate text-text-muted">
            {summarizePayload(event.payload)}
          </div>
        </div>
      </button>
      {open && (
        <div className="border-t border-border-subtle bg-base px-3 py-2">
          <pre className="overflow-x-auto whitespace-pre-wrap break-words font-mono text-[10px] text-text-muted">
            {JSON.stringify(event.payload, null, 2)}
          </pre>
          {event.source_session_id && (
            <div className="mt-2 text-[10px]">
              <Link
                to={`/chat?session=${event.source_session_id}`}
                className="text-accent hover:text-accent-hover"
              >
                view session →
              </Link>
            </div>
          )}
        </div>
      )}
    </li>
  );
}

function SessionRow({ session }: { session: Session }) {
  return (
    <li className="flex items-center justify-between px-3 py-2 text-xs">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="text-text">
            {session.routine_name ?? "(no routine)"}
          </span>
          <span className="rounded bg-status-active/10 px-1.5 py-0.5 text-[9px] uppercase text-status-active">
            {session.status}
          </span>
        </div>
        <div className="truncate font-mono text-[10px] text-text-dim">
          {session.id.slice(0, 8)} · {formatTimestamp(session.updated_at)}
        </div>
      </div>
      <Link
        to={`/chat?session=${session.id}`}
        className="text-accent hover:text-accent-hover"
      >
        view →
      </Link>
    </li>
  );
}

// --- helpers ---

function formatTimestamp(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    const diffSec = Math.floor(diffMs / 1000);
    if (diffSec < 60) return `${diffSec}s ago`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
    if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
    return d.toLocaleDateString();
  } catch {
    return iso;
  }
}

function summarizePayload(payload: Record<string, unknown>): string {
  if (!payload || typeof payload !== "object") return "";
  // Prefer common descriptive fields.
  for (const key of ["summary", "title", "message", "text", "type"]) {
    const v = payload[key];
    if (typeof v === "string" && v.length > 0) return v;
  }
  const keys = Object.keys(payload);
  if (keys.length === 0) return "(empty)";
  return keys.slice(0, 4).join(", ");
}
