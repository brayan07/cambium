import { NavLink } from "react-router";
import {
  MessageSquare,
  Inbox,
  ListTree,
  LayoutDashboard,
  BookOpen,
  Settings,
  PanelLeftClose,
  PanelLeftOpen,
} from "lucide-react";
import { useRequestSummary } from "../hooks/useRequests";

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
}

const navItems = [
  { to: "/chat", icon: MessageSquare, label: "Chat" },
  { to: "/inbox", icon: Inbox, label: "Inbox", badge: true },
  { to: "/work", icon: ListTree, label: "Work" },
  { to: "/dashboard", icon: LayoutDashboard, label: "Dashboard" },
  { to: "/memory", icon: BookOpen, label: "Memory" },
  { to: "/config", icon: Settings, label: "Config" },
];

export function Sidebar({ collapsed, onToggle }: SidebarProps) {
  const { data: summary } = useRequestSummary();

  // Count total pending requests for inbox badge
  const pendingCount = summary
    ? Object.values(summary.counts).reduce(
        (sum, statuses) => sum + (statuses.pending ?? 0),
        0,
      )
    : 0;

  return (
    <aside
      className={`flex h-screen flex-col border-r border-border bg-surface transition-[width] duration-150 ease-in-out ${
        collapsed ? "w-14" : "w-48"
      }`}
    >
      {/* Logo */}
      <div className="flex h-12 items-center border-b border-border px-3">
        {!collapsed && (
          <span className="font-display text-sm font-bold tracking-wide text-accent">
            CAMBIUM
          </span>
        )}
        {collapsed && (
          <span className="font-display text-sm font-bold text-accent">C</span>
        )}
      </div>

      {/* Navigation */}
      <nav className="flex flex-1 flex-col gap-0.5 px-2 py-3">
        {navItems.map(({ to, icon: Icon, label, badge }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              `group relative flex items-center gap-3 rounded px-2.5 py-2 text-sm transition-colors ${
                isActive
                  ? "border-l-2 border-accent bg-accent-dim text-accent"
                  : "border-l-2 border-transparent text-text-muted hover:bg-surface-raised hover:text-text"
              } ${collapsed ? "justify-center" : ""}`
            }
          >
            <Icon size={18} strokeWidth={1.5} />
            {!collapsed && <span>{label}</span>}
            {badge && pendingCount > 0 && (
              <span
                className={`flex h-4 min-w-4 items-center justify-center rounded-full bg-accent px-1 text-[10px] font-bold text-base ${
                  collapsed ? "absolute -right-0.5 -top-0.5" : "ml-auto"
                }`}
              >
                {pendingCount}
              </span>
            )}
          </NavLink>
        ))}
      </nav>

      {/* Collapse toggle */}
      <button
        onClick={onToggle}
        className="flex h-10 items-center justify-center border-t border-border text-text-dim transition-colors hover:text-text-muted"
      >
        {collapsed ? (
          <PanelLeftOpen size={16} />
        ) : (
          <PanelLeftClose size={16} />
        )}
      </button>
    </aside>
  );
}
