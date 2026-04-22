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
  ReferenceLine,
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
// Constants
// ---------------------------------------------------------------------------

const SIGNALS = [
  { key: "load1_ac_voltage",   label: "L1 Voltage",   unit: "V" },
  { key: "load1_ac_current",   label: "L1 Current",   unit: "A" },
  { key: "load1_active_power", label: "L1 Power",     unit: "W" },
  { key: "load1_frequency",    label: "L1 Frequency", unit: "Hz" },
  { key: "battery_voltage",    label: "Bat Voltage",  unit: "V" },
  { key: "battery_current",    label: "Bat Current",  unit: "A" },
  { key: "battery_soc",        label: "Bat SoC",      unit: "%" },
];

const SEVERITY_STYLE: Record<string, { badge: string; dot: string }> = {
  critical: { badge: "bg-red-500/15 text-red-400 border-red-500/20",   dot: "bg-red-500" },
  high:     { badge: "bg-amber-400/15 text-amber-400 border-amber-400/20", dot: "bg-amber-400" },
  medium:   { badge: "bg-blue-400/15 text-blue-400 border-blue-400/20",   dot: "bg-blue-400" },
};

function formatTs(iso: string) {
  try { return new Date(iso).toLocaleTimeString(); } catch { return iso; }
}

// ---------------------------------------------------------------------------
// Mini residual chart for one signal
// ---------------------------------------------------------------------------

function SignalChart({
  label,
  unit,
  data,
}: {
  label: string;
  unit: string;
  data: ResidualPoint[];
}) {
  if (!data.length) {
    return (
      <div className="bg-card border border-card-border rounded-xl p-4 flex flex-col gap-2">
        <p className="text-xs font-semibold text-foreground">{label}</p>
        <div className="h-32 flex items-center justify-center text-[10px] text-muted">
          No data yet
        </div>
      </div>
    );
  }

  // Build chart points — only include where we have both values
  const points = data
    .filter((d) => d.actual !== null && d.predicted !== null)
    .map((d) => ({
      t: formatTs(d.timestamp),
      actual: d.actual,
      predicted: d.predicted,
      anomaly: d.is_anomaly ? d.actual : null,
    }));

  return (
    <div className="bg-card border border-card-border rounded-xl p-4 flex flex-col gap-2">
      <div className="flex items-center justify-between">
        <p className="text-xs font-semibold text-foreground">{label}</p>
        <span className="text-[10px] text-muted">{unit}</span>
      </div>
      <ResponsiveContainer width="100%" height={120}>
        <ComposedChart data={points} margin={{ top: 4, right: 4, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" />
          <XAxis dataKey="t" hide />
          <YAxis
            width={36}
            tick={{ fontSize: 9, fill: "#6b7280" }}
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
            formatter={(v: number, name: string) => [
              `${v?.toFixed(3)} ${unit}`,
              name === "actual" ? "Actual" : name === "predicted" ? "Predicted" : "Anomaly",
            ]}
            labelFormatter={(l) => l}
          />
          {/* Predicted — dashed */}
          <Line
            type="monotone"
            dataKey="predicted"
            stroke="#3b82f6"
            strokeWidth={1}
            strokeDasharray="4 2"
            dot={false}
            isAnimationActive={false}
          />
          {/* Actual — solid */}
          <Line
            type="monotone"
            dataKey="actual"
            stroke="#22c55e"
            strokeWidth={1.5}
            dot={false}
            isAnimationActive={false}
          />
          {/* Anomaly dots — red */}
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Anomaly table row
// ---------------------------------------------------------------------------

function AnomalyRow({ r }: { r: AnomalyRecord }) {
  const s = SEVERITY_STYLE[r.severity] ?? SEVERITY_STYLE.medium;
  return (
    <tr className="border-b border-card-border hover:bg-background/40 transition-colors">
      <td className="px-3 py-2 text-[10px] text-muted font-mono whitespace-nowrap">
        {formatTs(r.timestamp)}
      </td>
      <td className="px-3 py-2 text-[10px] font-mono text-foreground">{r.signal}</td>
      <td className="px-3 py-2 text-[10px] font-mono text-right">{r.actual?.toFixed(3)}</td>
      <td className="px-3 py-2 text-[10px] font-mono text-right">{r.predicted?.toFixed(3)}</td>
      <td className="px-3 py-2 text-[10px] font-mono text-right">{r.z_score?.toFixed(2)}</td>
      <td className="px-3 py-2">
        <span className={`text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border ${s.badge}`}>
          {r.severity}
        </span>
      </td>
      <td className="px-3 py-2 text-center">
        {r.sustained && (
          <span className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border bg-red-500/20 text-red-400 border-red-500/30">
            yes
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
  const [page, setPage] = useState(0);
  const PAGE_SIZE = 20;

  const fetchAll = useCallback(async () => {
    try {
      // Residuals for all signals
      const residualResults = await Promise.all(
        SIGNALS.map((s) =>
          fetch(`${API_URL}/api/residuals/${s.key}?window=300`)
            .then((r) => r.json())
            .catch(() => [])
        )
      );
      const next: Record<string, ResidualPoint[]> = {};
      SIGNALS.forEach((s, i) => {
        const r = residualResults[i];
        next[s.key] = Array.isArray(r) ? r : [];
      });
      setResiduals(next);

      // Anomaly log
      const aData = await fetch(`${API_URL}/api/anomalies?limit=200`).then((r) => r.json()).catch(() => []);
      setAnomalies(Array.isArray(aData) ? aData : []);

      // Summary
      const sumData = await fetch(`${API_URL}/api/anomalies/summary`).then((r) => r.json()).catch(() => null);
      setSummary(sumData);
    } catch {
      // silently ignore — connection badge shows status
    }
  }, []);

  useEffect(() => {
    fetchAll();
    const id = setInterval(fetchAll, 10_000);
    return () => clearInterval(id);
  }, [fetchAll]);

  const filtered =
    severityFilter === "all"
      ? anomalies
      : anomalies.filter((a) => a.severity === severityFilter);
  const paged = filtered.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  const totalPages = Math.ceil(filtered.length / PAGE_SIZE);

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 rounded-lg bg-accent-blue/15 flex items-center justify-center">
          <IconWave className="w-5 h-5 text-accent-blue" />
        </div>
        <div>
          <h2 className="text-lg font-bold">Anomaly Monitor</h2>
          <p className="text-xs text-muted">SARIMA forecasting · residual-based detection</p>
        </div>
      </div>

      {/* Summary strip */}
      <div className="grid grid-cols-3 gap-3">
        {(["critical", "high", "medium"] as const).map((sev) => {
          const s = SEVERITY_STYLE[sev];
          const count = summary?.[sev] ?? 0;
          return (
            <div key={sev} className={`rounded-xl border p-4 ${s.badge}`}>
              <p className="text-2xl font-bold font-mono">{count}</p>
              <p className="text-[10px] uppercase tracking-wider mt-0.5 capitalize opacity-80">
                {sev} (24h)
              </p>
            </div>
          );
        })}
      </div>

      {/* Residual charts */}
      <div>
        <p className="text-[10px] font-semibold uppercase tracking-widest text-muted/70 mb-3">
          Residual Charts — last 5 minutes
        </p>
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-4 gap-3">
          {SIGNALS.map((s) => (
            <SignalChart
              key={s.key}
              label={s.label}
              unit={s.unit}
              data={residuals[s.key] ?? []}
            />
          ))}
        </div>
      </div>

      {/* Anomaly table */}
      <div className="bg-card border border-card-border rounded-xl overflow-hidden">
        {/* Table header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-card-border">
          <p className="text-xs font-semibold text-foreground">Anomaly Log</p>
          <div className="flex items-center gap-1 bg-background border border-card-border rounded-lg p-0.5">
            {(["all", "critical", "high", "medium"] as const).map((f) => (
              <button
                key={f}
                onClick={() => { setSeverityFilter(f); setPage(0); }}
                className={`px-2.5 py-1 text-[10px] font-medium rounded-md capitalize transition-colors ${
                  severityFilter === f
                    ? "bg-card text-foreground shadow-sm"
                    : "text-muted hover:text-foreground"
                }`}
              >
                {f === "all" ? `All (${anomalies.length})` : f}
              </button>
            ))}
          </div>
        </div>

        {filtered.length === 0 ? (
          <div className="py-16 text-center text-muted">
            <IconWave className="w-8 h-8 mx-auto mb-2 opacity-20" />
            <p className="text-sm">No anomalies detected</p>
            <p className="text-[10px] mt-1 opacity-60">SARIMA models are monitoring 7 signals</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="w-full text-left">
                <thead>
                  <tr className="border-b border-card-border bg-background/40">
                    {["Time", "Signal", "Actual", "Predicted", "Z-Score", "Severity", "Sustained"].map((h) => (
                      <th key={h} className="px-3 py-2 text-[9px] font-semibold uppercase tracking-wider text-muted">
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

            {/* Pagination */}
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
