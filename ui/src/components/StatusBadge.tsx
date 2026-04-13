import type { SessionStatus } from "../lib/types";

const statusConfig: Record<
  string,
  { label: string; color: string; pulse?: boolean }
> = {
  active: { label: "active", color: "bg-status-active", pulse: true },
  created: { label: "created", color: "bg-status-info" },
  completed: { label: "done", color: "bg-status-completed" },
  failed: { label: "failed", color: "bg-status-failed" },
  pending: { label: "pending", color: "bg-text-dim" },
  paused: { label: "paused", color: "bg-status-paused" },
};

interface StatusBadgeProps {
  status: SessionStatus | string;
}

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status] ?? {
    label: status,
    color: "bg-text-dim",
  };

  return (
    <span className="inline-flex items-center gap-1.5">
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${config.color} ${
          config.pulse ? "animate-pulse" : ""
        }`}
      />
      <span className="text-[11px] font-medium uppercase tracking-wider text-text-muted">
        {config.label}
      </span>
    </span>
  );
}
