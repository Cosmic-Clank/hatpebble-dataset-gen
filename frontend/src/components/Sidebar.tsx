"use client";

import React from "react";
import { useAuth, type Role } from "@/lib/auth-context";

export type Page =
  | "overview"
  | "battery"
  | "load1"
  | "load2"
  | "load3"
  | "controls-load1"
  | "controls-load2"
  | "controls-load3"
  | "alerts"
  | "anomalies"
  | "reports"
  | "ai-insights";

interface Props {
  active: Page;
  onNavigate: (page: Page) => void;
  alertBadge?: number;
}

interface NavItem {
  id: Page;
  label: string;
  icon: React.ReactNode;
  elevated?: boolean;
}

interface NavSection {
  title: string;
  items: NavItem[];
  elevated?: boolean;
}

// --- Icons as small components ---

function IconDashboard() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <rect x="3" y="3" width="7" height="7" rx="1.5" />
      <rect x="14" y="3" width="7" height="4" rx="1.5" />
      <rect x="14" y="11" width="7" height="10" rx="1.5" />
      <rect x="3" y="14" width="7" height="7" rx="1.5" />
    </svg>
  );
}

function IconBattery() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <rect x="6" y="4" width="12" height="18" rx="2" />
      <rect x="9" y="1" width="6" height="3" rx="1" />
      <path d="M10 14l2-3 2 3" />
    </svg>
  );
}

function IconBolt() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
    </svg>
  );
}

function IconSliders() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
    </svg>
  );
}

function IconSignOut() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
    </svg>
  );
}

const LOAD_LABELS: Record<string, string> = {
  load1: "Load Group 1",
  load2: "Load Group 2",
  load3: "Load Group 3",
};

function IconShield() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path d="M12 2l7 4v5c0 5-3.5 9.74-7 11-3.5-1.26-7-6-7-11V6l7-4z" />
    </svg>
  );
}

function IconWave() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path d="M2 12c1.5-3 3-4.5 4.5-4.5S9 9 10.5 9s3-3 4.5-3 3 1.5 4.5 4.5c1.5 3 3 4.5 3 4.5" />
    </svg>
  );
}

function IconFlow() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <circle cx="5" cy="12" r="2.5" />
      <circle cx="19" cy="6" r="2.5" />
      <circle cx="19" cy="18" r="2.5" />
      <path d="M7.5 12h4l3-5.5" />
      <path d="M11.5 12l3 5.5" />
    </svg>
  );
}

function IconTable() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <rect x="3" y="3" width="18" height="18" rx="2" />
      <path d="M3 9h18M3 15h18M9 3v18" />
    </svg>
  );
}

function IconSparkle() {
  return (
    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path d="M12 3v2m0 14v2M3 12h2m14 0h2M5.636 5.636l1.414 1.414M16.95 16.95l1.414 1.414M5.636 18.364l1.414-1.414M16.95 7.05l1.414-1.414" />
      <circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export default function Sidebar({ active, onNavigate, alertBadge = 0 }: Props) {
  const { user, role, signOut } = useAuth();

  const sections: NavSection[] = [
    {
      title: "General",
      items: [
        { id: "overview", label: "Overview", icon: <IconDashboard /> },
      ],
    },
    {
      title: "Monitoring",
      items: [
        { id: "battery", label: "Battery",      icon: <IconBattery /> },
        { id: "load1",   label: "Load Group 1", icon: <IconBolt /> },
        { id: "load2", label: "Load Group 2", icon: <IconBolt /> },
        { id: "load3", label: "Load Group 3", icon: <IconBolt /> },
      ],
    },
    {
      title: "Controls",
      elevated: true,
      items: [
        { id: "controls-load1", label: "Load Group 1", icon: <IconSliders />, elevated: true },
        { id: "controls-load2", label: "Load Group 2", icon: <IconSliders />, elevated: true },
        { id: "controls-load3", label: "Load Group 3", icon: <IconSliders />, elevated: true },
      ],
    },
    {
      title: "Security",
      items: [
        { id: "alerts",    label: "Alerts",           icon: <IconShield /> },
        { id: "anomalies", label: "Anomaly Monitor",  icon: <IconWave /> },
      ],
    },
    {
      title: "Analytics",
      items: [
        { id: "reports",     label: "Reports",     icon: <IconTable /> },
        { id: "ai-insights", label: "AI Insights", icon: <IconSparkle /> },
      ],
    },
  ];

  function activeHex(page: Page): string {
    if (page === "overview") return "#06b6d4";
    if (page === "battery") return "#22c55e";
    if (page.startsWith("controls")) return "#f59e0b";
    if (page === "alerts") return "#ef4444";
    if (page === "anomalies") return "#8b5cf6";
    if (page === "reports") return "#06b6d4";
    if (page === "ai-insights") return "#a855f7";
    return "#3b82f6";
  }

  return (
    <aside className="w-60 h-screen sticky top-0 flex flex-col bg-card border-r border-card-border">
      {/* Logo */}
      <div className="px-5 h-14 flex items-center gap-3 border-b border-card-border shrink-0">
        <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent-green to-accent-blue flex items-center justify-center">
          <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
            <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
          </svg>
        </div>
        <div>
          <span className="font-bold text-sm tracking-tight">Smart Grid</span>
          <span className="text-[10px] text-muted block -mt-0.5">EMS Dashboard</span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto py-4 px-3 space-y-6">
        {sections.map((section) => {
          if (section.elevated && role !== "elevated") return null;
          return (
            <div key={section.title}>
              <div className="px-2 mb-2 text-[10px] font-semibold uppercase tracking-widest text-muted/70">
                {section.title}
              </div>
              <div className="space-y-0.5">
                {section.items.map((item) => {
                  if (item.elevated && role !== "elevated") return null;
                  const isActive = active === item.id;
                  const hex = activeHex(item.id);
                  return (
                    <button
                      key={item.id}
                      onClick={() => onNavigate(item.id)}
                      className={`w-full flex items-center gap-3 px-3 py-2 text-sm rounded-lg transition-all ${
                        isActive
                          ? ""
                          : "text-muted hover:text-foreground hover:bg-background/50"
                      }`}
                      style={isActive ? { backgroundColor: `${hex}15`, color: hex } : undefined}
                    >
                      <span style={isActive ? { color: hex } : undefined}>{item.icon}</span>
                      <span className="font-medium">{item.label}</span>
                      {item.id === "alerts" && alertBadge > 0 && !isActive && (
                        <span className="ml-auto min-w-[18px] h-[18px] px-1 rounded-full bg-red-500 text-white text-[10px] font-bold flex items-center justify-center">
                          {alertBadge > 99 ? "99+" : alertBadge}
                        </span>
                      )}
                      {isActive && (
                        <span
                          className="ml-auto w-1.5 h-1.5 rounded-full"
                          style={{ backgroundColor: hex }}
                        />
                      )}
                    </button>
                  );
                })}
              </div>
            </div>
          );
        })}
      </nav>

      {/* User footer */}
      <div className="border-t border-card-border p-4 shrink-0 space-y-3">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded-full bg-background flex items-center justify-center text-xs font-bold text-muted uppercase">
            {user?.email?.charAt(0) ?? "?"}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-xs font-medium text-foreground truncate">{user?.email}</p>
            <span
              className={`text-[10px] font-bold uppercase tracking-wider ${
                role === "elevated" ? "text-accent-amber" : "text-accent-blue"
              }`}
            >
              {role}
            </span>
          </div>
        </div>
        <button
          onClick={signOut}
          className="w-full flex items-center gap-2 px-3 py-2 text-xs text-muted hover:text-accent-red hover:bg-accent-red/5 rounded-lg transition-all"
        >
          <IconSignOut />
          Sign out
        </button>
      </div>
    </aside>
  );
}
