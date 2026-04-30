"use client";

import React, { useEffect, useState, useCallback } from "react";
import {
  ResponsiveContainer,
  ComposedChart,
  Line,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

const API_URL =
  (process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000").replace(/^ws/, "http");

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface ResidualPoint {
  timestamp: string;
  predicted: number | null;
  actual: number | null;
  residual: number | null;
  z_score: number | null;
  is_anomaly: boolean;
}

interface AnomalyRecord {
  timestamp: string;
  signal: string;
  predicted: number;
  actual: number;
  residual: number;
  z_score: number;
  severity: "medium" | "high" | "critical";
  imputed: boolean;
  consecutive_anomaly_count: number;
  sustained: boolean;
}

// ---------------------------------------------------------------------------
// Signal groups — mirrors backend forecasting/config.py SIGNALS
// ---------------------------------------------------------------------------

interface SignalDef {
  key: string;
  label: string;
  unit: string;
}

interface SignalGroup {
  id: string;
  label: string;
  accent: string;
  signals: SignalDef[];
}

const SIGNAL_GROUPS: SignalGroup[] = [
  {
    id: "load1",
    label: "Load Group 1",
    accent: "#3b82f6",
    signals: [
      { key: "load1_ac_voltage",   label: "Voltage",   unit: "V"  },
      { key: "load1_ac_current",   label: "Current",   unit: "A"  },
      { key: "load1_active_power", label: "Power",     unit: "W"  },
      { key: "load1_frequency",    label: "Frequency", unit: "Hz" },
    ],
  },
  {
    id: "load2",
    label: "Load Group 2",
    accent: "#8b5cf6",
    signals: [
      { key: "load2_ac_voltage",   label: "Voltage",   unit: "V"  },
      { key: "load2_ac_current",   label: "Current",   unit: "A"  },
      { key: "load2_active_power", label: "Power",     unit: "W"  },
      { key: "load2_frequency",    label: "Frequency", unit: "Hz" },
    ],
  },
  {
    id: "load3",
    label: "Load Group 3",
    accent: "#f59e0b",
    signals: [
      { key: "load3_ac_voltage",   label: "Voltage",   unit: "V"  },
      { key: "load3_ac_current",   label: "Current",   unit: "A"  },
      { key: "load3_active_power", label: "Power",     unit: "W"  },
      { key: "load3_frequency",    label: "Frequency", unit: "Hz" },
    ],
  },
  {
    id: "battery",
    label: "Battery",
    accent: "#22c55e",
    signals: [
      { key: "battery_voltage", label: "Voltage", unit: "V" },
      { key: "battery_current", label: "Current", unit: "A" },
      { key: "battery_soc",     label: "SoC",     unit: "%" },
    ],
  },
];

const ALL_SIGNALS = SIGNAL_GROUPS.flatMap((g) => g.signals);

// Quick lookup: signal key → group accent colour
const SIGNAL_ACCENT: Record<string, string> = {};
for (const g of SIGNAL_GROUPS) {
  for (const s of g.signals) {
    SIGNAL_ACCENT[s.key] = g.accent;
  }
}

// ---------------------------------------------------------------------------
// Severity styles
// ---------------------------------------------------------------------------

const SEVERITY_STYLE: Record<string, { badge: string }> = {
  critical: { badge: "bg-red-500/15 text-red-400 border-red-500/20"       },
  high:     { badge: "bg-amber-400/15 text-amber-400 border-amber-400/20" },
  medium:   { badge: "bg-blue-400/15 text-blue-400 border-blue-400/20"    },
};

function formatTs(iso: string) {
  try { return new Date(iso).toLocaleTimeString(); } catch { return iso; }
}

// ---------------------------------------------------------------------------
// Signal chart
// ---------------------------------------------------------------------------

function SignalChart({
  label,
  unit,
  accent,
  data,
}: {
  label: string;
  unit: string;
  accent: string;
  data: ResidualPoint[];
}) {
  const points = data
    .filter((d) => d.actual !== null && d.predicted !== null)
    .map((d) => ({
      t:         formatTs(d.timestamp),
      actual:    d.actual,
      predicted: d.predicted,
      anomaly:   d.is_anomaly ? d.actual : null,
    }));

  return (
    <div className="bg-card border border-card-border rounded-xl p-4 flex flex-col gap-2"
         style={{ borderTopColor: accent, borderTopWidth: 2 }}>
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-foreground">{label}</p>
        <span className="text-[10px] text-muted font-mono">{unit}</span>
      </div>

      {!points.length ? (
        <div className="h-28 flex items-center justify-center text-[10px] text-muted">
          No data yet
        </div>
      ) : (
        <>
          <ResponsiveContainer width="100%" height={112}>
            <ComposedChart data={points} margin={{ top: 4, right: 2, bottom: 0, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
              <XAxis dataKey="t" hide />
              <YAxis
                width={34}
                tick={{ fontSize: 8, fill: "#6b7280" }}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip
                contentStyle={{
                  background: "#1a1a2e",
                  border: "1px solid rgba(255,255,255,0.1)",
                  borderRadius: 8,
                  fontSize: 10,
                }}
                formatter={(v: unknown, name: string) => [
                  `${Number(v).toFixed(3)} ${unit}`,
                  name === "actual" ? "Actual" : name === "predicted" ? "Predicted" : "Anomaly",
                ]}
                labelFormatter={(l) => l}
              />
              <Line
                type="monotone"
                dataKey="predicted"
                stroke="#3b82f6"
                strokeWidth={1}
                strokeDasharray="4 2"
                dot={false}
                isAnimationActive={false}
              />
              <Line
                type="monotone"
                dataKey="actual"
                stroke="#22c55e"
                strokeWidth={1.5}
                dot={false}
                isAnimationActive={false}
              />
              <Scatter dataKey="anomaly" fill="#ef4444" r={3} isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>

          <div className="flex items-center gap-3 text-[9px] text-muted">
            <span className="flex items-center gap-1">
              <span className="w-4 border-t border-green-500 inline-block" />
              Actual
            </span>
            <span className="flex items-center gap-1">
              <span className="w-4 border-t border-dashed border-blue-400 inline-block" />
              Predicted
            </span>
            <span className="flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-red-500 inline-block" />
              Anomaly
            </span>
          </div>
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Anomaly table row
// ---------------------------------------------------------------------------

function AnomalyRow({ r }: { r: AnomalyRecord }) {
  const s = SEVERITY_STYLE[r.severity] ?? SEVERITY_STYLE.medium;
  const accent = SIGNAL_ACCENT[r.signal] ?? "#6b7280";

  return (
    <tr className="border-b border-card-border hover:bg-background/40 transition-colors">
      <td className="px-3 py-2 text-[10px] text-muted font-mono whitespace-nowrap">
        {formatTs(r.timestamp)}
      </td>
      <td className="px-3 py-2">
        <div className="flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 rounded-full shrink-0" style={{ backgroundColor: accent }} />
          <span className="text-[10px] font-mono text-foreground">{r.signal}</span>
        </div>
      </td>
      <td className="px-3 py-2 text-[10px] font-mono text-right tabular-nums">
        {r.actual?.toFixed(3)}
      </td>
      <td className="px-3 py-2 text-[10px] font-mono text-right tabular-nums">
        {r.predicted?.toFixed(3)}
      </td>
      <td className="px-3 py-2 text-[10px] font-mono text-right tabular-nums">
        {r.z_score?.toFixed(2)}
      </td>
      <td className="px-3 py-2">
        <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border ${s.badge}`}>
          {r.severity}
        </span>
      </td>
      <td className="px-3 py-2 text-center">
        {r.sustained && (
          <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border bg-red-500/20 text-red-400 border-red-500/30">
            sustained
          </span>
        )}
      </td>
    </tr>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

export default function AnomalyMonitor() {
  const [residuals, setResiduals] = useState<Record<string, ResidualPoint[]>>({});
  const [anomalies, setAnomalies] = useState<AnomalyRecord[]>([]);
  const [summary, setSummary] = useState<{ critical: number; high: number; medium: number } | null>(null);
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [groupFilter, setGroupFilter] = useState<string>("all");
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;

  const fetchAll = useCallback(async () => {
    try {
      const residualResults = await Promise.all(
        ALL_SIGNALS.map((s) =>
          fetch(`${API_URL}/api/residuals/${s.key}?window=300`)
            .then((r) => r.json())
            .catch(() => [])
        )
      );
      const next: Record<string, ResidualPoint[]> = {};
      ALL_SIGNALS.forEach((s, i) => {
        const r = residualResults[i];
        next[s.key] = Array.isArray(r) ? r : [];
      });
      setResiduals(next);

      const aData = await fetch(`${API_URL}/api/anomalies?limit=500`)
        .then((r) => r.json()).catch(() => []);
      setAnomalies(Array.isArray(aData) ? aData : []);

      const sumData = await fetch(`${API_URL}/api/anomalies/summary`)
        .then((r) => r.json()).catch(() => null);
      setSummary(sumData);
    } catch {
      // connection badge shows status
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 10_000);
    return () => clearInterval(id);
  }, [fetchAll]);

  // Filtering
  const filtered = anomalies.filter((a) => {
    const sevOk = severityFilter === "all" || a.severity === severityFilter;
    const grpOk = groupFilter === "all" || a.signal.startsWith(groupFilter);
    return sevOk && grpOk;
  });
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);
  const paged = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  function setFilter(sev: string, grp: string) {
    setSeverityFilter(sev);
    setGroupFilter(grp);
    setPage(0);
  }

  return (
    <div className="flex flex-col gap-6">

      {/* ── Header ── */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-accent-blue/15 flex items-center justify-center">
          <IconWave className="w-5 h-5 text-accent-blue" />
        </div>
        <div>
          <h2 className="text-lg font-bold">Anomaly Monitor</h2>
          <p className="text-xs text-muted">
            XGBoost forecasting · residual-based detection ·{" "}
            <span className="text-foreground font-medium">{ALL_SIGNALS.length} signals</span>
          </p>
        </div>
      </div>

      {/* ── Summary strip ── */}
      <div className="grid grid-cols-3 gap-3">
        {(["critical", "high", "medium"] as const).map((sev) => {
          const s = SEVERITY_STYLE[sev];
          const count = summary?.[sev] ?? 0;
          return (
            <button
              key={sev}
              onClick={() => setFilter(sev, "all")}
              className={`rounded-xl border p-4 text-left transition-opacity hover:opacity-80 ${s.badge} ${severityFilter === sev ? "ring-2 ring-current ring-offset-1 ring-offset-background" : ""}`}
            >
              <p className="text-2xl font-bold font-mono">{count}</p>
              <p className="text-[10px] uppercase tracking-wider mt-0.5 capitalize opacity-80">
                {sev} (24 h)
              </p>
            </button>
          );
        })}
      </div>

      {/* ── Residual charts — per group ── */}
      <div className="flex flex-col gap-6">
        {SIGNAL_GROUPS.map((group) => (
          <div key={group.id}>
            {/* Group header */}
            <div className="flex items-center gap-2 mb-3">
              <span
                className="w-2 h-2 rounded-full shrink-0"
                style={{ backgroundColor: group.accent }}
              />
              <p
                className="text-[10px] font-semibold uppercase tracking-widest"
                style={{ color: group.accent }}
              >
                {group.label}
              </p>
              <div className="flex-1 h-px bg-card-border" />
              <span className="text-[10px] text-muted">{group.signals.length} signals · last 5 min</span>
            </div>

            {/* Charts grid — 4 cols on xl, 2 on smaller */}
            <div className="grid grid-cols-2 xl:grid-cols-4 gap-3">
              {group.signals.map((sig) => (
                <SignalChart
                  key={sig.key}
                  label={sig.label}
                  unit={sig.unit}
                  accent={group.accent}
                  data={residuals[sig.key] ?? []}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      {/* ── Anomaly table ── */}
      <div className="bg-card border border-card-border rounded-xl overflow-hidden">

        {/* Table toolbar */}
        <div className="flex flex-wrap items-center justify-between gap-2 px-4 py-3 border-b border-card-border">
          <p className="text-xs font-semibold text-foreground">
            Anomaly Log
            <span className="ml-2 text-muted font-normal">{filtered.length} events</span>
          </p>

          <div className="flex flex-wrap items-center gap-2">
            {/* Group filter */}
            <div className="flex items-center gap-0.5 bg-background border border-card-border rounded-lg p-0.5">
              <button
                onClick={() => setFilter(severityFilter, "all")}
                className={`px-2 py-1 text-[10px] font-medium rounded-md transition-colors ${groupFilter === "all" ? "bg-card text-foreground shadow-sm" : "text-muted hover:text-foreground"}`}
              >
                All groups
              </button>
              {SIGNAL_GROUPS.map((g) => (
                <button
                  key={g.id}
                  onClick={() => setFilter(severityFilter, g.id)}
                  className={`px-2 py-1 text-[10px] font-medium rounded-md transition-colors ${groupFilter === g.id ? "bg-card text-foreground shadow-sm" : "text-muted hover:text-foreground"}`}
                  style={groupFilter === g.id ? { color: g.accent } : undefined}
                >
                  {g.id === "battery" ? "Bat" : g.label.replace("Load Group ", "L")}
                </button>
              ))}
            </div>

            {/* Severity filter */}
            <div className="flex items-center gap-0.5 bg-background border border-card-border rounded-lg p-0.5">
              {(["all", "critical", "high", "medium"] as const).map((f) => (
                <button
                  key={f}
                  onClick={() => setFilter(f, groupFilter)}
                  className={`px-2 py-1 text-[10px] font-medium rounded-md capitalize transition-colors ${severityFilter === f ? "bg-card text-foreground shadow-sm" : "text-muted hover:text-foreground"}`}
                >
                  {f === "all" ? "All sev" : f}
                </button>
              ))}
            </div>

            {(severityFilter !== "all" || groupFilter !== "all") && (
              <button
                onClick={() => setFilter("all", "all")}
                className="px-2 py-1 text-[10px] text-muted hover:text-foreground border border-card-border rounded-md transition-colors"
              >
                Clear ×
              </button>
            )}
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="py-16 text-center text-muted">
            <IconWave className="w-8 h-8 mx-auto mb-2 opacity-20" />
            <p className="text-sm">No anomalies detected</p>
            <p className="text-[10px] mt-1 opacity-60">
              Monitoring {ALL_SIGNALS.length} signals across {SIGNAL_GROUPS.length} groups
            </p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-card-border bg-background/40">
                    {["Time", "Signal", "Actual", "Predicted", "Z-Score", "Severity", ""].map((h) => (
                      <th
                        key={h}
                        className="px-3 py-2 text-[9px] font-semibold uppercase tracking-wider text-muted"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {paged.map((r, i) => (
                    <AnomalyRow key={`${r.timestamp}-${r.signal}-${i}`} r={r} />
                  ))}
                </tbody>
              </table>
            </div>

            {totalPages > 1 && (
              <div className="flex items-center justify-between px-4 py-3 border-t border-card-border">
                <span className="text-[10px] text-muted">
                  {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, filtered.length)} of {filtered.length}
                </span>
                <div className="flex gap-1">
                  <button
                    onClick={() => setPage((p) => Math.max(0, p - 1))}
                    disabled={page === 0}
                    className="px-2.5 py-1 text-[10px] rounded border border-card-border text-muted hover:text-foreground disabled:opacity-30 transition-colors"
                  >
                    ‹ Prev
                  </button>
                  <button
                    onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
                    disabled={page >= totalPages - 1}
                    className="px-2.5 py-1 text-[10px] rounded border border-card-border text-muted hover:text-foreground disabled:opacity-30 transition-colors"
                  >
                    Next ›
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
}

function IconWave({ className }: { className?: string }) {
  return (
    <svg className={className} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
      <path d="M2 12c1.5-3 3-4.5 4.5-4.5S9 9 10.5 9s3-3 4.5-3 3 1.5 4.5 4.5c1.5 3 3 4.5 3 4.5" />
    </svg>
  );
}
