import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  User as UserIcon,
  Check,
  X,
  Clock,
  Ban,
  CirclePlay,
  Circle,
} from "lucide-react";
import {
  useWorkItems,
  useWorkItem,
  useWorkItemEvents,
  useBlockWorkItem,
  useUnblockWorkItem,
  useCompleteWorkItem,
  buildWorkItemTree,
  filterTreeByStatus,
  type WorkItemNode,
} from "../hooks/useWorkItems";
import type { WorkItem, WorkItemEvent, WorkItemStatus } from "../lib/types";

const ALL_STATUSES: WorkItemStatus[] = [
  "pending",
  "ready",
  "active",
  "blocked",
  "completed",
  "failed",
  "canceled",
];

/**
 * Work items carry a session_id stamped from the JWT of whoever last touched
 * them. Non-routine actors use sentinel values that don't correspond to real
 * sessions — don't render these as clickable session links.
 */
const NON_SESSION_SENTINELS = new Set(["ui", "human", "auto_rollup", ""]);

function isRealSessionId(id: string | null): id is string {
  return !!id && !NON_SESSION_SENTINELS.has(id);
}

const DEFAULT_VISIBLE: WorkItemStatus[] = [
  "pending",
  "ready",
  "active",
  "blocked",
];

export function WorkPage() {
  const { data, isLoading } = useWorkItems();
  const [visible, setVisible] = useState<Set<WorkItemStatus>>(
    () => new Set(DEFAULT_VISIBLE),
  );
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [searchParams] = useSearchParams();
  const deepLinkedRef = useRef<string | null>(null);

  // Deep-link: ?item=<id> jumps the detail panel to that item and expands
  // its ancestor chain so it's visible in the tree.
  useEffect(() => {
    const itemId = searchParams.get("item");
    if (!itemId || !data) return;
    if (deepLinkedRef.current === itemId) return;
    const byId = new Map(data.items.map((i) => [i.id, i]));
    if (!byId.has(itemId)) return;
    deepLinkedRef.current = itemId;

    setSelectedId(itemId);
    setExpanded((prev) => {
      const next = new Set(prev);
      let cursor: string | null = byId.get(itemId)?.parent_id ?? null;
      while (cursor) {
        next.add(cursor);
        cursor = byId.get(cursor)?.parent_id ?? null;
      }
      return next;
    });
  }, [searchParams, data]);

  const tree = useMemo(() => {
    if (!data) return [];
    const full = buildWorkItemTree(data.items);
    return filterTreeByStatus(full, visible);
  }, [data, visible]);

  const toggleStatus = (status: WorkItemStatus) => {
    setVisible((prev) => {
      const next = new Set(prev);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  };

  const toggleExpand = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  return (
    <div className="flex h-full">
      {/* Tree pane */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex items-center gap-4 border-b border-border px-6 py-3">
          <h1 className="font-display text-sm font-semibold text-text">
            Work Items
          </h1>
          <div className="flex gap-1">
            {ALL_STATUSES.map((s) => (
              <button
                key={s}
                onClick={() => toggleStatus(s)}
                className={`rounded px-2 py-0.5 text-[10px] uppercase tracking-wide transition-colors ${
                  visible.has(s)
                    ? "bg-accent-dim text-accent"
                    : "text-text-dim hover:text-text-muted"
                }`}
              >
                {s}
              </button>
            ))}
          </div>
          {data?.truncated && (
            <span className="text-[10px] text-status-paused">
              showing {data.limit} of {data.total}
            </span>
          )}
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-2">
          {isLoading && (
            <div className="flex h-32 items-center justify-center text-sm text-text-dim">
              Loading...
            </div>
          )}
          {!isLoading && tree.length === 0 && (
            <div className="flex h-32 items-center justify-center text-sm text-text-dim">
              No work items match the current filters.
            </div>
          )}
          {tree.map((node) => (
            <TreeNode
              key={node.item.id}
              node={node}
              expanded={expanded}
              selectedId={selectedId}
              onToggle={toggleExpand}
              onSelect={setSelectedId}
            />
          ))}
        </div>
      </div>

      {/* Detail pane */}
      <div className="w-96 flex-shrink-0 border-l border-border overflow-y-auto">
        <DetailPanel
          id={selectedId}
          onClose={() => setSelectedId(null)}
          onNavigate={setSelectedId}
        />
      </div>
    </div>
  );
}

/* --- Tree --- */

function TreeNode({
  node,
  expanded,
  selectedId,
  onToggle,
  onSelect,
}: {
  node: WorkItemNode;
  expanded: Set<string>;
  selectedId: string | null;
  onToggle: (id: string) => void;
  onSelect: (id: string) => void;
}) {
  const { item, children } = node;
  const hasChildren = children.length > 0;
  const isExpanded = expanded.has(item.id);
  const isSelected = selectedId === item.id;
  const isUserTask = item.assigned_to === "user";

  return (
    <div>
      <div
        className={`group flex items-center gap-1 rounded px-1 py-1 text-xs transition-colors ${
          isSelected
            ? "bg-accent-dim text-accent"
            : "hover:bg-surface/50"
        }`}
        style={{ paddingLeft: `${node.depth * 16 + 4}px` }}
      >
        <button
          onClick={() => hasChildren && onToggle(item.id)}
          className="flex h-4 w-4 items-center justify-center text-text-dim"
          aria-label={hasChildren ? "toggle" : undefined}
        >
          {hasChildren ? (
            isExpanded ? (
              <ChevronDown size={12} />
            ) : (
              <ChevronRight size={12} />
            )
          ) : (
            <span className="h-1 w-1 rounded-full bg-text-dim/30" />
          )}
        </button>
        <StatusIcon status={item.status} />
        <button
          onClick={() => onSelect(item.id)}
          className="flex-1 min-w-0 truncate text-left"
          title={item.title}
        >
          {item.title}
        </button>
        {isUserTask && (
          <UserIcon
            size={11}
            className="flex-shrink-0 text-accent"
            aria-label="user task"
          />
        )}
        {isRealSessionId(item.session_id) && item.status === "active" && (
          <Link
            to={`/chat?session=${item.session_id}`}
            onClick={(e) => e.stopPropagation()}
            className="flex-shrink-0 text-text-dim hover:text-accent"
            title="Observe session"
          >
            <ExternalLink size={11} />
          </Link>
        )}
      </div>
      {isExpanded &&
        children.map((child) => (
          <TreeNode
            key={child.item.id}
            node={child}
            expanded={expanded}
            selectedId={selectedId}
            onToggle={onToggle}
            onSelect={onSelect}
          />
        ))}
    </div>
  );
}

function StatusIcon({ status }: { status: WorkItemStatus }) {
  const map: Record<
    WorkItemStatus,
    { icon: typeof Circle; className: string; label: string }
  > = {
    pending: { icon: Circle, className: "text-text-dim", label: "pending" },
    ready: { icon: CirclePlay, className: "text-status-paused", label: "ready" },
    active: { icon: CirclePlay, className: "text-status-active", label: "active" },
    blocked: { icon: Ban, className: "text-status-failed", label: "blocked" },
    completed: { icon: Check, className: "text-status-active/60", label: "completed" },
    failed: { icon: X, className: "text-status-failed", label: "failed" },
    canceled: { icon: X, className: "text-text-dim/50", label: "canceled" },
  };
  const { icon: Icon, className, label } = map[status];
  return <Icon size={11} className={className} aria-label={label} />;
}

/* --- Detail panel --- */

function DetailPanel({
  id,
  onClose,
  onNavigate,
}: {
  id: string | null;
  onClose: () => void;
  onNavigate: (id: string) => void;
}) {
  const { data: item, isLoading } = useWorkItem(id);
  const { data: events } = useWorkItemEvents(id);
  const blockMut = useBlockWorkItem();
  const unblockMut = useUnblockWorkItem();
  const completeMut = useCompleteWorkItem();

  if (!id) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-text-dim">
        Select a work item to see details.
      </div>
    );
  }
  if (isLoading || !item) {
    return (
      <div className="flex h-full items-center justify-center text-xs text-text-dim">
        Loading...
      </div>
    );
  }

  const isUserTask = item.assigned_to === "user";
  const isBusy = blockMut.isPending || unblockMut.isPending || completeMut.isPending;

  return (
    <div className="flex flex-col gap-4 p-4">
      {/* Header */}
      <div>
        <div className="mb-1 flex items-start gap-2">
          <StatusIcon status={item.status} />
          <h2 className="flex-1 text-sm font-semibold text-text">
            {item.title}
          </h2>
          <button
            onClick={onClose}
            className="text-text-dim hover:text-text-muted"
            aria-label="close"
          >
            <X size={14} />
          </button>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-[10px] text-text-dim">
          <span className="uppercase tracking-wide">{item.status}</span>
          <span>·</span>
          <span>priority {item.priority}</span>
          {item.actor && (
            <>
              <span>·</span>
              <span>{item.actor}</span>
            </>
          )}
          {isUserTask && (
            <>
              <span>·</span>
              <span className="text-accent">user task</span>
            </>
          )}
        </div>
      </div>

      {/* Description */}
      {item.description && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wide text-text-dim">
            Description
          </div>
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-muted">
            {item.description}
          </p>
        </div>
      )}

      {/* Session link */}
      {isRealSessionId(item.session_id) && (
        <div>
          <Link
            to={`/chat?session=${item.session_id}`}
            className="inline-flex items-center gap-1 text-[11px] text-text-dim transition-colors hover:text-accent"
          >
            <ExternalLink size={11} />
            View session
          </Link>
        </div>
      )}

      {/* Dependencies */}
      {item.depends_on.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wide text-text-dim">
            Depends on
          </div>
          <ul className="space-y-0.5">
            {item.depends_on.map((d) => (
              <li key={d}>
                <DependencyLink id={d} onNavigate={onNavigate} />
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Result */}
      {item.result && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wide text-text-dim">
            Result
          </div>
          <p className="whitespace-pre-wrap text-xs leading-relaxed text-text-muted">
            {item.result}
          </p>
        </div>
      )}

      {/* Context */}
      {Object.keys(item.context).length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wide text-text-dim">
            Context
          </div>
          <pre className="overflow-x-auto rounded border border-border bg-base px-2 py-1.5 font-mono text-[10px] text-text-muted">
            {JSON.stringify(item.context, null, 2)}
          </pre>
        </div>
      )}

      {/* Actions */}
      <div className="flex flex-wrap gap-2 border-t border-border pt-3">
        {isUserTask && item.status !== "completed" && (
          <button
            onClick={() => completeMut.mutate({ id: item.id })}
            disabled={isBusy}
            className="flex items-center gap-1 rounded border border-status-active/40 bg-status-active/10 px-2 py-1 text-[11px] text-status-active transition-colors hover:bg-status-active/20 disabled:opacity-40"
          >
            <Check size={11} /> Mark Complete
          </button>
        )}
        {item.status === "blocked" ? (
          <button
            onClick={() => unblockMut.mutate(item.id)}
            disabled={isBusy}
            className="rounded border border-border px-2 py-1 text-[11px] text-text-muted transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
          >
            Unblock
          </button>
        ) : (
          <button
            onClick={() => {
              const reason = window.prompt("Reason for blocking?");
              if (reason) blockMut.mutate({ id: item.id, reason });
            }}
            disabled={
              isBusy || item.status === "completed" || item.status === "failed"
            }
            className="rounded border border-border px-2 py-1 text-[11px] text-text-dim transition-colors hover:border-status-failed hover:text-status-failed disabled:opacity-40"
          >
            <Ban size={11} className="mr-1 inline" /> Block
          </button>
        )}
      </div>

      {/* Events */}
      {events && events.length > 0 && (
        <div>
          <div className="mb-1 text-[10px] uppercase tracking-wide text-text-dim">
            Events
          </div>
          <ul className="space-y-1.5">
            {events.map((e) => (
              <EventRow key={e.id} event={e} />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function EventRow({ event }: { event: WorkItemEvent }) {
  const data = event.data ?? {};
  const str = (k: string): string | undefined => {
    const v = (data as Record<string, unknown>)[k];
    return typeof v === "string" ? v : undefined;
  };

  let label: React.ReactNode = event.event_type;
  let body: React.ReactNode = null;

  switch (event.event_type) {
    case "status_changed": {
      const from = str("from");
      const to = str("to");
      label = (
        <>
          {from ?? "?"} <span className="text-text-dim">→</span> {to ?? "?"}
        </>
      );
      break;
    }
    case "status_forced": {
      // Emitted by _force_status for rollup auto-complete and review rejection.
      const to = str("to");
      const reason = str("reason");
      label = (
        <>
          forced → {to ?? "?"}
          {reason && (
            <span className="text-text-dim"> · {reason}</span>
          )}
        </>
      );
      break;
    }
    case "created": {
      label = "created";
      const parent = str("parent_id");
      if (parent) {
        body = (
          <div className="text-text-dim">under {parent.slice(0, 8)}</div>
        );
      }
      break;
    }
    case "claimed":
      label = "claimed";
      break;
    case "result_set": {
      label = "result";
      const result = str("result");
      if (result) {
        body = (
          <div className="whitespace-pre-wrap text-text-dim">
            {result.length > 200 ? result.slice(0, 200) + "…" : result}
          </div>
        );
      }
      break;
    }
    case "reviewed": {
      // Only fires on acceptance; rejection goes through status_forced.
      const verdict = str("verdict");
      const reviewedBy = str("reviewed_by");
      label = (
        <>
          reviewed <span className="text-text-dim">·</span>{" "}
          <span className="text-status-active">{verdict ?? "accepted"}</span>
          {reviewedBy && (
            <span className="text-text-dim"> by {reviewedBy}</span>
          )}
        </>
      );
      break;
    }
    case "context_updated": {
      const merged = (data as Record<string, unknown>)["merged_keys"];
      const keys = Array.isArray(merged) ? (merged as string[]) : [];
      label = "context updated";
      if (keys.length > 0) {
        body = <div className="text-text-dim">keys: {keys.join(", ")}</div>;
      }
      break;
    }
    case "dependency_added":
      label = "dependency added";
      if (str("dependency_id"))
        body = (
          <div className="font-mono text-text-dim">
            {str("dependency_id")!.slice(0, 8)}
          </div>
        );
      break;
    case "dependency_removed":
      label = "dependency removed";
      if (str("dependency_id"))
        body = (
          <div className="font-mono text-text-dim">
            {str("dependency_id")!.slice(0, 8)}
          </div>
        );
      break;
    case "reparented": {
      const oldP = str("from_parent");
      const newP = str("to_parent");
      label = (
        <>
          reparented{" "}
          <span className="text-text-dim">
            {oldP?.slice(0, 8) ?? "∅"} → {newP?.slice(0, 8) ?? "∅"}
          </span>
        </>
      );
      break;
    }
    case "children_created": {
      const children = (data as Record<string, unknown>)["child_ids"];
      const count = Array.isArray(children) ? children.length : undefined;
      label = count != null ? `decomposed (${count} children)` : "decomposed";
      break;
    }
    default:
      label = event.event_type;
  }

  return (
    <li className="flex gap-2 text-[11px] text-text-muted">
      <Clock size={10} className="mt-0.5 flex-shrink-0 text-text-dim" />
      <div className="min-w-0 flex-1">
        <div className="font-medium">{label}</div>
        {body}
        <div className="text-[10px] text-text-dim">
          {formatTime(event.created_at)}
          {event.actor && <span> · {event.actor}</span>}
        </div>
      </div>
    </li>
  );
}

function DependencyLink({
  id,
  onNavigate,
}: {
  id: string;
  onNavigate: (id: string) => void;
}) {
  const { data: dep } = useWorkItem(id);
  return (
    <button
      onClick={() => onNavigate(id)}
      className="flex w-full items-center gap-1.5 text-left text-[11px] text-text-muted transition-colors hover:text-accent"
      title={id}
    >
      {dep ? (
        <>
          <StatusIcon status={dep.status} />
          <span className="truncate">{dep.title}</span>
        </>
      ) : (
        <span className="font-mono text-text-dim">{id.slice(0, 8)}</span>
      )}
    </button>
  );
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// Silence unused-import warning for WorkItem type referenced indirectly.
export type { WorkItem };
