"use client";

import React, { useEffect, useRef, useState } from "react";
import ConnectionBadge from "./ConnectionBadge";

interface Alert {
  id: string;
  timestamp: string;
  rule: string;
  label: string;
  severity: "info" | "warning" | "critical";
  topic: string;
  message: string;
  data: Record<string, unknown>;
}

type Filter = "all" | "critical" | "warning" | "info";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";


const SEVERITY_STYLES: Record<string, { dot: string; badge: string; row: string }> = {
  critical: {
    dot:   "bg-red-500",
    badge: "bg-red-500/15 text-red-400 border-red-500/20",
    row:   "border-red-500/20 bg-red-500/5",
  },
  warning: {
    dot:   "bg-amber-400",
    badge: "bg-amber-400/15 text-amber-400 border-amber-400/20",
    row:   "border-amber-400/20 bg-amber-400/5",
  },
  info: {
    dot:   "bg-blue-400",
    badge: "bg-blue-400/15 text-blue-400 border-blue-400/20",
    row:   "border-blue-400/20 bg-blue-400/5",
  },
};

function formatTs(iso: string): string {
  try {
    return new Date(iso).toLocaleTimeString();
  } catch {
    return iso;
  }
}

interface Props {
  /** Called with the total unseen count so the sidebar badge can update */
  onUnseenChange?: (count: number) => void;
}

export default function AlertsFeed({ onUnseenChange }: Props) {
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [filter, setFilter] = useState<Filter>("all");
  const [connected, setConnected] = useState(false);
  const unseenRef = useRef(0);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    let ws: WebSocket;
    let dead = false;

    function connect() {
      ws = new WebSocket(`${WS_URL}/ws/alerts`);
      wsRef.current = ws;

      ws.onopen = () => !dead && setConnected(true);

      ws.onmessage = (e) => {
        if (dead) return;
        try {
          const alert: Alert = JSON.parse(e.data);
          setAlerts((prev) => {
            // Avoid duplicates (history re-send on reconnect)
            if (prev.some((a) => a.id === alert.id)) return prev;
            return [alert, ...prev];
          });
          unseenRef.current += 1;
          onUnseenChange?.(unseenRef.current);
        } catch {
          // ignore malformed frame
        }
      };

      ws.onclose = () => {
        if (!dead) {
          setConnected(false);
          setTimeout(connect, 2000);
        }
      };
    }

    connect();
    return () => {
      dead = true;
      ws?.close();
    };
  }, []);

  // Reset unseen count when this page is mounted / in view
  useEffect(() => {
    unseenRef.current = 0;
    onUnseenChange?.(0);
  }, []);

  function clearAlerts() {
    setAlerts([]);
    unseenRef.current = 0;
    onUnseenChange?.(0);
  }

  const filtered = filter === "all" ? alerts : alerts.filter((a) => a.severity === filter);

  const counts = {
    critical: alerts.filter((a) => a.severity === "critical").length,
    warning:  alerts.filter((a) => a.severity === "warning").length,
    info:     alerts.filter((a) => a.severity === "info").length,
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-red-500/10 flex items-center justify-center">
            <IconShield className="w-5 h-5 text-red-400" />
          </div>
          <div>
            <h2 className="text-lg font-bold">Security Alerts</h2>
            <p className="text-xs text-muted">
              {alerts.length} alert{alerts.length !== 1 ? "s" : ""} &middot; IDS engine active
            </p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            onClick={clearAlerts}
            className="text-xs text-muted hover:text-foreground px-3 py-1.5 rounded-lg border border-card-border hover:border-foreground/20 transition-colors"
          >
            Clear
          </button>
          <ConnectionBadge connected={connected} />
        </div>
      </div>

      {/* Summary chips */}
      <div className="grid grid-cols-3 gap-3">
        {(["critical", "warning", "info"] as const).map((sev) => (
          <button
            key={sev}
            onClick={() => setFilter(filter === sev ? "all" : sev)}
            className={`rounded-xl border p-3 text-left transition-colors ${
              filter === sev
                ? SEVERITY_STYLES[sev].row + " " + SEVERITY_STYLES[sev].badge
                : "bg-card border-card-border hover:border-muted/30"
            }`}
          >
            <p className="text-lg font-bold font-mono">{counts[sev]}</p>
            <p className="text-[10px] uppercase tracking-wider text-muted capitalize mt-0.5">{sev}</p>
          </button>
        ))}
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-1 bg-card border border-card-border rounded-xl p-1">
        {(["all", "critical", "warning", "info"] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={`flex-1 py-1.5 text-xs font-medium rounded-lg capitalize transition-colors ${
              filter === f
                ? "bg-background text-foreground shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            {f === "all" ? `All (${alerts.length})` : f}
          </button>
        ))}
      </div>

      {/* Alert list */}
      <div className="flex flex-col gap-2">
        {filtered.length === 0 ? (
          <div className="text-center py-16 text-muted">
            <IconShield className="w-10 h-10 mx-auto mb-3 opacity-20" />
            <p className="text-sm">No {filter === "all" ? "" : filter + " "}alerts</p>
            <p className="text-xs mt-1 opacity-60">The IDS is watching all MQTT traffic</p>
          </div>
        ) : (
          filtered.map((alert) => {
            const s = SEVERITY_STYLES[alert.severity] ?? SEVERITY_STYLES.info;
            const hasData = Object.keys(alert.data ?? {}).length > 0;
            return (
              <AlertRow key={alert.id} alert={alert} s={s} hasData={hasData} />
            );
          })
        )}
      </div>
    </div>
  );
}

function AlertRow({
  alert,
  s,
  hasData,
}: {
  alert: Alert;
  s: { dot: string; badge: string; row: string };
  hasData: boolean;
}) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className={`rounded-xl border p-4 ${s.row}`}>
      <div className="flex items-start gap-3">
        <span className={`mt-1.5 w-2 h-2 rounded-full shrink-0 ${s.dot}`} />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap mb-1">
            <span className={`text-[10px] font-bold uppercase tracking-wider px-1.5 py-0.5 rounded border ${s.badge}`}>
              {alert.severity}
            </span>
            <span className="text-xs font-semibold text-foreground">
              {alert.label}
            </span>
            <span className="text-[10px] text-muted font-mono ml-auto shrink-0">
              {formatTs(alert.timestamp)}
            </span>
          </div>
          <p className="text-xs text-foreground/80">{alert.message}</p>
          <p className="text-[10px] text-muted font-mono mt-1">{alert.topic}</p>

          {hasData && (
            <>
              <button
                onClick={() => setExpanded((v) => !v)}
                className="mt-2 text-[10px] text-muted hover:text-foreground flex items-center gap-1 transition-colors"
              >
                <span>{expanded ? "▾" : "▸"}</span>
                {expanded ? "Hide" : "Show"} details
              </button>
              {expanded && (
                <div className="mt-2 rounded-lg bg-background/60 border border-card-border overflow-hidden">
                  {Object.entries(alert.data).map(([k, v], i, arr) => (
                    <div
                      key={k}
                      className={`grid grid-cols-2 px-3 py-1.5 ${i < arr.length - 1 ? "border-b border-card-border" : ""}`}
                    >
                      <span className="text-[10px] text-muted uppercase tracking-wider">{k}</span>
                      <span className="text-[10px] font-mono text-foreground">{String(v)}</span>
                    </div>
                  ))}
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  );
}

function IconShield({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path d="M12 2l7 4v5c0 5-3.5 9.74-7 11-3.5-1.26-7-6-7-11V6l7-4z" />
    </svg>
  );
}
