import { useState, useCallback } from "react";
import { Link } from "react-router";
import {
  useRequests,
  useAnswerRequest,
  useRejectRequest,
} from "../hooks/useRequests";
import {
  useUserTasks,
  useCompleteWorkItem,
} from "../hooks/useWorkItems";
import type { Request, RequestStatus, WorkItem } from "../lib/types";
import {
  ShieldQuestion,
  MessageSquareText,
  SlidersHorizontal,
  ClipboardList,
  Check,
  X,
  Clock,
  ChevronDown,
  ChevronUp,
  ExternalLink,
  ListTodo,
} from "lucide-react";

const STATUS_TABS: { label: string; value: RequestStatus | "all" }[] = [
  { label: "Pending", value: "pending" },
  { label: "Answered", value: "answered" },
  { label: "All", value: "all" },
];

const TYPE_ICONS: Record<string, typeof ShieldQuestion> = {
  permission: ShieldQuestion,
  information: MessageSquareText,
  preference: SlidersHorizontal,
  survey: ClipboardList,
};

const TYPE_LABELS: Record<string, string> = {
  permission: "Permission",
  information: "Information",
  preference: "Preference",
  survey: "Survey",
};

export function InboxPage() {
  const [statusFilter, setStatusFilter] = useState<RequestStatus | "all">(
    "pending",
  );

  const { data: requests, isLoading } = useRequests(
    statusFilter === "all" ? undefined : statusFilter,
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header */}
      <div className="flex items-center gap-4 border-b border-border px-6 py-3">
        <h1 className="font-display text-sm font-semibold text-text">Inbox</h1>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Tasks for you */}
        <TasksSection />

        {/* Requests subheader */}
        <div className="flex items-center gap-3 border-b border-border bg-surface/40 px-6 py-2">
          <ShieldQuestion size={13} className="text-text-dim" />
          <div className="font-display text-[11px] uppercase tracking-wide text-text-muted">
            Requests
          </div>
          <div className="flex gap-1">
            {STATUS_TABS.map((tab) => (
              <button
                key={tab.value}
                onClick={() => setStatusFilter(tab.value)}
                className={`rounded px-2 py-0.5 text-[11px] transition-colors ${
                  statusFilter === tab.value
                    ? "bg-accent-dim text-accent"
                    : "text-text-dim hover:text-text-muted"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* Request list */}
        {isLoading && (
          <div className="flex h-32 items-center justify-center text-sm text-text-dim">
            Loading...
          </div>
        )}

        {!isLoading && (!requests || requests.length === 0) && (
          <div className="flex h-full flex-col items-center justify-center gap-2 text-center">
            <div className="text-sm text-text-dim">
              {statusFilter === "pending"
                ? "No pending requests"
                : "No requests found"}
            </div>
            <div className="text-xs text-text-dim/60">
              Requests from routines will appear here when they need your input.
            </div>
          </div>
        )}

        {requests && requests.length > 0 && (
          <div className="divide-y divide-border">
            {requests.map((req) => (
              <RequestCard key={req.id} request={req} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function RequestCard({ request }: { request: Request }) {
  const [expanded, setExpanded] = useState(request.status === "pending");
  const [answer, setAnswer] = useState(request.default ?? "");
  const answerMutation = useAnswerRequest();
  const rejectMutation = useRejectRequest();

  const isPending = request.status === "pending";
  const Icon = TYPE_ICONS[request.type] ?? ClipboardList;

  const handleAnswer = useCallback(
    (value: string) => {
      if (!value.trim()) return;
      answerMutation.mutate({ id: request.id, answer: value });
    },
    [answerMutation, request.id],
  );

  const handleReject = useCallback(() => {
    rejectMutation.mutate(request.id);
  }, [rejectMutation, request.id]);

  const isBusy = answerMutation.isPending || rejectMutation.isPending;

  return (
    <div
      className={`px-6 py-3 transition-colors ${
        isPending ? "bg-base" : "bg-surface/30"
      }`}
    >
      {/* Header row */}
      <button
        onClick={() => setExpanded((p) => !p)}
        className="flex w-full items-center gap-3 text-left"
      >
        <Icon
          size={16}
          className={isPending ? "text-accent" : "text-text-dim/40"}
        />
        <div className="flex-1 min-w-0">
          <div
            className={`text-sm ${isPending ? "text-text" : "text-text-muted"}`}
          >
            {request.summary}
          </div>
          <div className="flex items-center gap-2 text-[10px] text-text-dim">
            <span>{TYPE_LABELS[request.type] ?? request.type}</span>
            <span>·</span>
            <span>{request.created_by ?? "unknown"}</span>
            <span>·</span>
            <span>{formatRelativeTime(request.created_at)}</span>
            {isPending && <ExpiryIndicator request={request} />}
            {request.status !== "pending" && (
              <>
                <span>·</span>
                <StatusBadge status={request.status} />
              </>
            )}
          </div>
        </div>
        {expanded ? (
          <ChevronUp size={14} className="text-text-dim" />
        ) : (
          <ChevronDown size={14} className="text-text-dim" />
        )}
      </button>

      {/* Expanded content */}
      {expanded && (
        <div className="mt-3 ml-7">
          {/* Source session link */}
          {request.session_id && request.session_id !== "seed-session" && (
            <Link
              to={`/chat?session=${request.session_id}`}
              className="mb-2 inline-flex items-center gap-1 text-[11px] text-text-dim transition-colors hover:text-accent"
              onClick={(e) => e.stopPropagation()}
            >
              <ExternalLink size={11} />
              View source session
            </Link>
          )}

          {/* Detail text */}
          {request.detail && (
            <p className="mb-3 text-xs leading-relaxed text-text-muted">
              {request.detail}
            </p>
          )}

          {/* Answered state */}
          {request.status === "answered" && request.answer && (
            <div className="rounded border border-status-active/20 bg-status-active/5 px-3 py-2 text-xs text-text-muted">
              <span className="font-medium text-status-active">Answer:</span>{" "}
              {request.answer}
            </div>
          )}

          {/* Rejected state */}
          {request.status === "rejected" && (
            <div className="rounded border border-status-failed/20 bg-status-failed/5 px-3 py-2 text-xs text-text-dim">
              Rejected
            </div>
          )}

          {/* Expired state */}
          {request.status === "expired" && (
            <div className="rounded border border-border px-3 py-2 text-xs text-text-dim">
              <Clock size={12} className="mr-1 inline" />
              Expired
            </div>
          )}

          {/* Pending — answer controls */}
          {isPending && (
            <div className="mt-1">
              {request.type === "permission" ? (
                <PermissionControls
                  onAnswer={handleAnswer}
                  onReject={handleReject}
                  disabled={isBusy}
                />
              ) : request.options && request.options.length > 0 ? (
                <OptionsControls
                  options={request.options}
                  defaultValue={request.default}
                  onAnswer={handleAnswer}
                  onReject={handleReject}
                  disabled={isBusy}
                />
              ) : (
                <FreeformControls
                  value={answer}
                  onChange={setAnswer}
                  onAnswer={() => handleAnswer(answer)}
                  onReject={handleReject}
                  disabled={isBusy}
                />
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/* --- Tasks for you --- */

function TasksSection() {
  const { data: tasks, isLoading } = useUserTasks();
  const completeMut = useCompleteWorkItem();

  if (isLoading) return null;
  if (!tasks || tasks.length === 0) return null;

  return (
    <>
      <div className="flex items-center gap-3 border-b border-border bg-surface/40 px-6 py-2">
        <ListTodo size={13} className="text-text-dim" />
        <div className="font-display text-[11px] uppercase tracking-wide text-text-muted">
          Tasks for you
        </div>
        <div className="text-[10px] text-text-dim">{tasks.length}</div>
      </div>
      <div className="divide-y divide-border">
        {tasks.map((task) => (
          <TaskCard
            key={task.id}
            task={task}
            onComplete={() => completeMut.mutate({ id: task.id })}
            disabled={completeMut.isPending}
          />
        ))}
      </div>
    </>
  );
}

function TaskCard({
  task,
  onComplete,
  disabled,
}: {
  task: WorkItem;
  onComplete: () => void;
  disabled: boolean;
}) {
  return (
    <div className="px-6 py-3 transition-colors">
      <div className="flex items-center gap-3">
        <ListTodo size={16} className="text-accent" />
        <div className="flex-1 min-w-0">
          <div className="text-sm text-text">{task.title}</div>
          <div className="flex items-center gap-2 text-[10px] text-text-dim">
            <span className="uppercase tracking-wide">{task.status}</span>
            <span>·</span>
            <span>priority {task.priority}</span>
            {task.actor && (
              <>
                <span>·</span>
                <span>assigned by {task.actor}</span>
              </>
            )}
          </div>
          {task.description && (
            <p className="mt-1 text-xs leading-relaxed text-text-muted">
              {task.description}
            </p>
          )}
        </div>
        <div className="flex flex-shrink-0 items-center gap-2">
          <Link
            to={`/work?item=${task.id}`}
            className="inline-flex items-center gap-1 text-[11px] text-text-dim transition-colors hover:text-accent"
            title="Open in work tree"
          >
            <ExternalLink size={11} />
            View in tree
          </Link>
          <button
            onClick={onComplete}
            disabled={disabled}
            className="flex items-center gap-1 rounded border border-status-active/40 bg-status-active/10 px-2.5 py-1 text-[11px] text-status-active transition-colors hover:bg-status-active/20 disabled:opacity-40"
          >
            <Check size={11} /> Mark Complete
          </button>
        </div>
      </div>
    </div>
  );
}

/* --- Answer control variants --- */

function PermissionControls({
  onAnswer,
  onReject,
  disabled,
}: {
  onAnswer: (v: string) => void;
  onReject: () => void;
  disabled: boolean;
}) {
  return (
    <div className="flex gap-2">
      <button
        onClick={() => onAnswer("approved")}
        disabled={disabled}
        className="flex items-center gap-1.5 rounded border border-status-active/40 bg-status-active/10 px-3 py-1.5 text-xs text-status-active transition-colors hover:bg-status-active/20 disabled:opacity-40"
      >
        <Check size={12} /> Approve
      </button>
      <button
        onClick={onReject}
        disabled={disabled}
        className="flex items-center gap-1.5 rounded border border-status-failed/40 bg-status-failed/10 px-3 py-1.5 text-xs text-status-failed transition-colors hover:bg-status-failed/20 disabled:opacity-40"
      >
        <X size={12} /> Deny
      </button>
    </div>
  );
}

function OptionsControls({
  options,
  defaultValue,
  onAnswer,
  onReject,
  disabled,
}: {
  options: string[];
  defaultValue: string | null;
  onAnswer: (v: string) => void;
  onReject: () => void;
  disabled: boolean;
}) {
  const [selected, setSelected] = useState(defaultValue ?? options[0] ?? "");

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-wrap gap-1.5">
        {options.map((opt) => (
          <button
            key={opt}
            onClick={() => setSelected(opt)}
            className={`rounded border px-2.5 py-1 text-xs transition-colors ${
              selected === opt
                ? "border-accent bg-accent-dim text-accent"
                : "border-border text-text-dim hover:border-text-dim hover:text-text-muted"
            }`}
          >
            {opt}
            {opt === defaultValue && (
              <span className="ml-1 text-[9px] text-text-dim/60">default</span>
            )}
          </button>
        ))}
      </div>
      <div className="flex gap-2">
        <button
          onClick={() => onAnswer(selected)}
          disabled={disabled || !selected}
          className="flex items-center gap-1.5 rounded border border-accent/40 bg-accent-dim px-3 py-1.5 text-xs text-accent transition-colors hover:bg-accent hover:text-base disabled:opacity-40"
        >
          <Check size={12} /> Submit
        </button>
        {defaultValue && (
          <button
            onClick={() => onAnswer(defaultValue)}
            disabled={disabled}
            className="rounded border border-border px-3 py-1.5 text-xs text-text-muted transition-colors hover:border-accent hover:text-accent disabled:opacity-40"
            title={`Submit the default: ${defaultValue}`}
          >
            Use default
          </button>
        )}
        <button
          onClick={onReject}
          disabled={disabled}
          className="rounded border border-border px-3 py-1.5 text-xs text-text-dim transition-colors hover:border-status-failed hover:text-status-failed disabled:opacity-40"
          title="Tell the routine not to wait for an answer"
        >
          Reject
        </button>
      </div>
    </div>
  );
}

function FreeformControls({
  value,
  onChange,
  onAnswer,
  onReject,
  disabled,
}: {
  value: string;
  onChange: (v: string) => void;
  onAnswer: () => void;
  onReject: () => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-col gap-2">
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="Type your answer..."
        rows={2}
        className="resize-none rounded border border-border bg-base px-3 py-2 font-mono text-xs text-text placeholder:text-text-dim focus:border-accent focus:outline-none"
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            onAnswer();
          }
        }}
      />
      <div className="flex gap-2">
        <button
          onClick={onAnswer}
          disabled={disabled || !value.trim()}
          className="flex items-center gap-1.5 rounded border border-accent/40 bg-accent-dim px-3 py-1.5 text-xs text-accent transition-colors hover:bg-accent hover:text-base disabled:opacity-40"
        >
          <Check size={12} /> Submit
        </button>
        <button
          onClick={onReject}
          disabled={disabled}
          className="rounded border border-border px-3 py-1.5 text-xs text-text-dim transition-colors hover:border-status-failed hover:text-status-failed disabled:opacity-40"
          title="Tell the routine not to wait for an answer"
        >
          Reject
        </button>
      </div>
    </div>
  );
}

/* --- Utilities --- */

// Only preference and survey requests are actually expired by the backend
// sweeper (see consumer/loop.py _sweep_expired_requests). Permission and
// information requests block indefinitely even if timeout_hours is set, so
// we don't show a countdown for them.
const EXPIRABLE_TYPES = new Set(["preference", "survey"]);

function ExpiryIndicator({ request }: { request: Request }) {
  if (!request.timeout_hours || !EXPIRABLE_TYPES.has(request.type)) return null;

  const createdMs = new Date(request.created_at).getTime();
  const deadlineMs = createdMs + request.timeout_hours * 3600_000;
  const remainingMs = deadlineMs - Date.now();

  if (remainingMs <= 0) {
    // Past deadline but sweeper hasn't run yet (throttled to 60s). Show a
    // neutral "expiring..." — the answer endpoint may still accept it.
    return (
      <>
        <span>·</span>
        <span className="text-status-failed">expiring...</span>
      </>
    );
  }

  const totalWindowMs = request.timeout_hours * 3600_000;
  const fractionLeft = remainingMs / totalWindowMs;
  const urgentMs = 5 * 60_000; // final 5 minutes

  let color = "text-text-dim";
  if (remainingMs <= urgentMs) color = "text-status-failed";
  else if (fractionLeft < 0.25) color = "text-status-paused";

  return (
    <>
      <span>·</span>
      <Clock size={10} className={color} />
      <span className={color}>expires in {formatDuration(remainingMs)}</span>
    </>
  );
}

function formatDuration(ms: number): string {
  const totalSec = Math.floor(ms / 1000);
  const hours = Math.floor(totalSec / 3600);
  const minutes = Math.floor((totalSec % 3600) / 60);
  if (hours > 0) return minutes > 0 ? `${hours}h ${minutes}m` : `${hours}h`;
  if (minutes > 0) return `${minutes}m`;
  const seconds = totalSec % 60;
  return `${seconds}s`;
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    answered: "text-status-active",
    rejected: "text-status-failed",
    expired: "text-text-dim/60",
    pending: "text-accent",
  };
  return (
    <span className={`font-medium ${styles[status] ?? "text-text-dim"}`}>
      {status}
    </span>
  );
}

function formatRelativeTime(isoString: string): string {
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;
  const diffMin = Math.floor(diffMs / 60_000);

  if (diffMin < 1) return "just now";
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffHr = Math.floor(diffMin / 60);
  if (diffHr < 24) return `${diffHr}h ago`;
  const diffDay = Math.floor(diffHr / 24);
  return `${diffDay}d ago`;
}
