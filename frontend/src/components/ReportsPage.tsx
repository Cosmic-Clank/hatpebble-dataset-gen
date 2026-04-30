"use client";

import React, { useCallback, useMemo, useState } from "react";

const API_URL =
  (process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000").replace(/^ws/, "http");

// ─── Types ────────────────────────────────────────────────────────────────────

type Source = "sensor" | "anomaly" | "alert";
type SortDir = "asc" | "desc";
type Preset = "1h" | "24h" | "7d" | "custom";

const PAGE_SIZE = 50;

const SENSORS = [
  { id: "battery", label: "Battery" },
  { id: "load1",   label: "Load Group 1" },
  { id: "load2",   label: "Load Group 2" },
  { id: "load3",   label: "Load Group 3" },
];

const BATTERY_NUM_COLS  = ["battery_voltage","battery_current","battery_power","soc","temperature","consumed_ah","time_to_go"];
const LOAD_NUM_COLS     = ["ac_voltage","ac_current","active_power","active_energy","frequency","power_factor"];
const ANOMALY_SEVERITIES = ["all","critical","high","medium"] as const;
const ALERT_SEVERITIES   = ["all","critical","warning","info"] as const;

const ALL_SIGNALS = [
  "load1_ac_voltage","load1_ac_current","load1_active_power","load1_frequency",
  "load2_ac_voltage","load2_ac_current","load2_active_power","load2_frequency",
  "load3_ac_voltage","load3_ac_current","load3_active_power","load3_frequency",
  "battery_voltage","battery_current","battery_soc",
];

// ─── Helpers ──────────────────────────────────────────────────────────────────

function toLocalDatetimeInput(d: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function presetRange(p: Preset): { from: string; to: string } {
  const now = new Date();
  const from = new Date(now);
  if (p === "1h")  from.setHours(now.getHours() - 1);
  if (p === "24h") from.setDate(now.getDate() - 1);
  if (p === "7d")  from.setDate(now.getDate() - 7);
  return { from: toLocalDatetimeInput(from), to: toLocalDatetimeInput(now) };
}

function localInputToIso(s: string): string {
  if (!s) return "";
  return new Date(s).toISOString();
}

function fmtTs(iso: string) {
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function fmtNum(v: unknown, dp = 2): string {
  if (v === null || v === undefined || v === "") return "—";
  const n = Number(v);
  return isNaN(n) ? String(v) : n.toFixed(dp);
}

function exportCsv(records: Record<string, unknown>[], filename: string) {
  if (!records.length) return;
  const headers = Object.keys(records[0]);
  const rows = records.map(r =>
    headers.map(h => {
      const v = r[h];
      if (v === null || v === undefined) return "";
      const s = String(v);
      return s.includes(",") || s.includes('"') || s.includes("\n")
        ? `"${s.replace(/"/g, '""')}"` : s;
    }).join(",")
  );
  const csv = [headers.join(","), ...rows].join("\n");
  const blob = new Blob([csv], { type: "text/csv" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}

// ─── Small UI atoms ───────────────────────────────────────────────────────────

function Chip({
  active, onClick, children, color,
}: { active: boolean; onClick: () => void; children: React.ReactNode; color?: string }) {
  return (
    <button
      onClick={onClick}
      className={`px-3 py-1 rounded-full text-[11px] font-semibold border transition-all ${
        active
          ? "border-transparent"
          : "border-card-border text-muted hover:text-foreground hover:border-foreground/30"
      }`}
      style={active ? { backgroundColor: color ?? "#3b82f6", color: "#fff", borderColor: color ?? "#3b82f6" } : undefined}
    >
      {children}
    </button>
  );
}

function RangeInput({
  label, min, max, onMin, onMax,
}: { label: string; min: string; max: string; onMin: (v: string) => void; onMax: (v: string) => void }) {
  return (
    <div className="flex flex-col gap-1">
      <span className="text-[10px] text-muted uppercase tracking-wider">{label}</span>
      <div className="flex gap-1 items-center">
        <input
          type="number"
          placeholder="Min"
          value={min}
          onChange={e => onMin(e.target.value)}
          className="w-20 bg-background border border-card-border rounded px-2 py-1 text-[11px] font-mono text-foreground placeholder:text-muted focus:outline-none focus:border-accent-blue"
        />
        <span className="text-muted text-[10px]">–</span>
        <input
          type="number"
          placeholder="Max"
          value={max}
          onChange={e => onMax(e.target.value)}
          className="w-20 bg-background border border-card-border rounded px-2 py-1 text-[11px] font-mono text-foreground placeholder:text-muted focus:outline-none focus:border-accent-blue"
        />
      </div>
    </div>
  );
}

function StatPill({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex flex-col items-center px-4 py-2 bg-background rounded-lg border border-card-border">
      <span className="text-[9px] uppercase tracking-widest text-muted">{label}</span>
      <span className="text-sm font-mono font-bold text-foreground mt-0.5">{value}</span>
    </div>
  );
}

// ─── Main component ───────────────────────────────────────────────────────────

export default function ReportsPage() {
  // ── Source & time ──
  const [source, setSource]   = useState<Source>("anomaly");
  const [preset, setPreset]   = useState<Preset>("24h");
  const [timeFrom, setTimeFrom] = useState(() => presetRange("24h").from);
  const [timeTo,   setTimeTo]   = useState(() => presetRange("24h").to);

  // ── Fetch state ──
  const [loading,    setLoading]    = useState(false);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [rawRecords, setRawRecords] = useState<Record<string, unknown>[]>([]);
  const [hasFetched, setHasFetched] = useState(false);

  // ── Sensor filters ──
  const [sensorId,  setSensorId]  = useState("battery");
  const [colRanges, setColRanges] = useState<Record<string, { min: string; max: string }>>({});

  // ── Anomaly filters ──
  const [signalFilter,  setSignalFilter]  = useState("all");
  const [anomalySev,    setAnomalySev]    = useState("all");
  const [zMin,          setZMin]          = useState("");
  const [zMax,          setZMax]          = useState("");
  const [sustainedOnly, setSustainedOnly] = useState(false);

  // ── Alert filters ──
  const [alertSev,    setAlertSev]    = useState("all");
  const [ruleFilter,  setRuleFilter]  = useState("all");
  const [topicSearch, setTopicSearch] = useState("");

  // ── Table state ──
  const [sortCol, setSortCol] = useState("timestamp");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [page,    setPage]    = useState(0);

  // ── Preset picker ──
  function applyPreset(p: Preset) {
    setPreset(p);
    if (p !== "custom") {
      const r = presetRange(p);
      setTimeFrom(r.from);
      setTimeTo(r.to);
    }
  }

  // ── Clear all filters ──
  function clearFilters() {
    setColRanges({});
    setSignalFilter("all"); setAnomalySev("all"); setZMin(""); setZMax(""); setSustainedOnly(false);
    setAlertSev("all"); setRuleFilter("all"); setTopicSearch("");
    setPage(0);
  }

  // ── Fetch ──
  const fetchRecords = useCallback(async () => {
    setLoading(true);
    setFetchError(null);
    setPage(0);
    try {
      const fromIso = localInputToIso(timeFrom);
      const toIso   = localInputToIso(timeTo);
      let url = "";

      if (source === "sensor") {
        url = `${API_URL}/api/logs/sensor?sensor=${sensorId}&from=${encodeURIComponent(fromIso)}&to=${encodeURIComponent(toIso)}&limit=10000`;
      } else if (source === "anomaly") {
        url = `${API_URL}/api/anomalies?limit=5000&from=${encodeURIComponent(fromIso)}&to=${encodeURIComponent(toIso)}`;
        // Note: /api/anomalies uses `since` for from — alias both
        url = `${API_URL}/api/anomalies?limit=5000&since=${encodeURIComponent(fromIso)}&to=${encodeURIComponent(toIso)}`;
      } else {
        url = `${API_URL}/api/logs/alerts?from=${encodeURIComponent(fromIso)}&to=${encodeURIComponent(toIso)}&limit=10000`;
      }

      const res = await fetch(url);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setRawRecords(Array.isArray(data) ? data : []);
      setHasFetched(true);
    } catch (e) {
      setFetchError(e instanceof Error ? e.message : "Fetch failed");
      setRawRecords([]);
    } finally {
      setLoading(false);
    }
  }, [source, sensorId, timeFrom, timeTo]);

  // ── Derived: unique rules from fetched alert data ──
  const uniqueRules = useMemo(
    () => source === "alert"
      ? ["all", ...Array.from(new Set(rawRecords.map(r => String(r.rule ?? "")))).filter(Boolean)]
      : [],
    [rawRecords, source]
  );

  // ── Client-side filtering ──
  const filtered = useMemo(() => {
    let rows = [...rawRecords];

    if (source === "sensor") {
      const numCols = sensorId === "battery" ? BATTERY_NUM_COLS : LOAD_NUM_COLS;
      for (const col of numCols) {
        const range = colRanges[col];
        if (!range) continue;
        if (range.min !== "") {
          const mn = parseFloat(range.min);
          if (!isNaN(mn)) rows = rows.filter(r => Number(r[col]) >= mn);
        }
        if (range.max !== "") {
          const mx = parseFloat(range.max);
          if (!isNaN(mx)) rows = rows.filter(r => Number(r[col]) <= mx);
        }
      }
    }

    if (source === "anomaly") {
      if (signalFilter !== "all") rows = rows.filter(r => r.signal === signalFilter);
      if (anomalySev   !== "all") rows = rows.filter(r => r.severity === anomalySev);
      if (zMin !== "") { const mn = parseFloat(zMin); if (!isNaN(mn)) rows = rows.filter(r => Math.abs(Number(r.z_score)) >= mn); }
      if (zMax !== "") { const mx = parseFloat(zMax); if (!isNaN(mx)) rows = rows.filter(r => Math.abs(Number(r.z_score)) <= mx); }
      if (sustainedOnly) rows = rows.filter(r => r.sustained === true);
    }

    if (source === "alert") {
      if (alertSev   !== "all") rows = rows.filter(r => r.severity === alertSev);
      if (ruleFilter !== "all") rows = rows.filter(r => r.rule === ruleFilter);
      if (topicSearch) {
        const q = topicSearch.toLowerCase();
        rows = rows.filter(r => String(r.topic ?? "").toLowerCase().includes(q));
      }
    }

    return rows;
  }, [rawRecords, source, sensorId, colRanges, signalFilter, anomalySev, zMin, zMax, sustainedOnly, alertSev, ruleFilter, topicSearch]);

  // ── Client-side sort ──
  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const av = a[sortCol] ?? "";
      const bv = b[sortCol] ?? "";
      const cmp = av < bv ? -1 : av > bv ? 1 : 0;
      return sortDir === "asc" ? cmp : -cmp;
    });
  }, [filtered, sortCol, sortDir]);

  // ── Pagination ──
  const totalPages = Math.max(1, Math.ceil(sorted.length / PAGE_SIZE));
  const paged = sorted.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  // ── Summary stats ──
  const stats = useMemo(() => {
    if (!filtered.length) return null;
    if (source === "sensor") {
      const powerCol = sensorId === "battery" ? "battery_power" : "active_power";
      const vals = filtered.map(r => Number(r[powerCol])).filter(n => !isNaN(n));
      if (!vals.length) return { count: filtered.length };
      const avg = vals.reduce((s, v) => s + v, 0) / vals.length;
      return { count: filtered.length, avgPower: avg, minPower: Math.min(...vals), maxPower: Math.max(...vals) };
    }
    if (source === "anomaly") {
      const zVals = filtered.map(r => Math.abs(Number(r.z_score))).filter(n => !isNaN(n));
      const avgZ = zVals.length ? zVals.reduce((s, v) => s + v, 0) / zVals.length : 0;
      const maxZ = zVals.length ? Math.max(...zVals) : 0;
      const critical = filtered.filter(r => r.severity === "critical").length;
      return { count: filtered.length, avgZ, maxZ, critical };
    }
    if (source === "alert") {
      const critical = filtered.filter(r => r.severity === "critical").length;
      const warning  = filtered.filter(r => r.severity === "warning").length;
      const info     = filtered.filter(r => r.severity === "info").length;
      return { count: filtered.length, critical, warning, info };
    }
    return { count: filtered.length };
  }, [filtered, source, sensorId]);

  // ── Column definitions ──
  const columns = useMemo((): string[] => {
    if (!rawRecords.length) {
      if (source === "sensor") return sensorId === "battery" ? BATTERY_NUM_COLS : LOAD_NUM_COLS;
      if (source === "anomaly") return ["timestamp","signal","severity","actual","predicted","z_score","sustained"];
      return ["timestamp","rule","severity","topic","message"];
    }
    return Object.keys(rawRecords[0]);
  }, [rawRecords, source, sensorId]);

  function handleSort(col: string) {
    if (sortCol === col) setSortDir(d => d === "asc" ? "desc" : "asc");
    else { setSortCol(col); setSortDir("asc"); }
    setPage(0);
  }

  function setColRange(col: string, side: "min" | "max", val: string) {
    setColRanges(prev => ({ ...prev, [col]: { ...(prev[col] ?? { min: "", max: "" }), [side]: val } }));
    setPage(0);
  }

  const numCols = sensorId === "battery" ? BATTERY_NUM_COLS : LOAD_NUM_COLS;

  const sevColor: Record<string, string> = {
    critical: "#ef4444", high: "#f97316", medium: "#f59e0b",
    warning: "#f59e0b", info: "#3b82f6",
  };

  const exportFilename = `${source}_${timeFrom.slice(0,10)}_${timeTo.slice(0,10)}.csv`;

  // ─────────────────────────────────────────────────────────────────────────────

  return (
    <div className="flex flex-col gap-5">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-bold">Reports</h1>
        <p className="text-xs text-muted mt-0.5">Query, filter and export historical sensor records</p>
      </div>

      {/* Source tabs */}
      <div className="flex gap-2">
        {(["sensor","anomaly","alert"] as Source[]).map(s => {
          const label = s === "sensor" ? "Sensor Readings" : s === "anomaly" ? "Anomalies" : "Security Alerts";
          const color = s === "sensor" ? "#3b82f6" : s === "anomaly" ? "#8b5cf6" : "#ef4444";
          return (
            <button
              key={s}
              onClick={() => { setSource(s); setRawRecords([]); setHasFetched(false); clearFilters(); }}
              className={`px-4 py-2 rounded-lg text-sm font-semibold border transition-all ${
                source === s ? "text-white" : "text-muted border-card-border hover:text-foreground"
              }`}
              style={source === s ? { backgroundColor: color, borderColor: color } : undefined}
            >
              {label}
            </button>
          );
        })}
      </div>

      {/* Filter panel */}
      <div className="bg-card border border-card-border rounded-xl p-5 flex flex-col gap-5">

        {/* Time range */}
        <div className="flex flex-col gap-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted">Time Range</span>
          <div className="flex flex-wrap gap-2 items-center">
            {(["1h","24h","7d","custom"] as Preset[]).map(p => (
              <Chip key={p} active={preset === p} onClick={() => applyPreset(p)} color="#06b6d4">
                {p === "1h" ? "Last 1 hour" : p === "24h" ? "Last 24 hours" : p === "7d" ? "Last 7 days" : "Custom"}
              </Chip>
            ))}
          </div>
          <div className="flex flex-wrap gap-3 items-center">
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted uppercase tracking-wider">From</span>
              <input
                type="datetime-local"
                value={timeFrom}
                onChange={e => { setTimeFrom(e.target.value); setPreset("custom"); }}
                className="bg-background border border-card-border rounded px-3 py-1.5 text-xs text-foreground focus:outline-none focus:border-accent-blue"
              />
            </div>
            <div className="flex flex-col gap-1">
              <span className="text-[10px] text-muted uppercase tracking-wider">To</span>
              <input
                type="datetime-local"
                value={timeTo}
                onChange={e => { setTimeTo(e.target.value); setPreset("custom"); }}
                className="bg-background border border-card-border rounded px-3 py-1.5 text-xs text-foreground focus:outline-none focus:border-accent-blue"
              />
            </div>
          </div>
        </div>

        <div className="border-t border-card-border" />

        {/* Source-specific filters */}
        {source === "sensor" && (
          <div className="flex flex-col gap-4">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">Sensor & Column Filters</span>
            <div className="flex flex-wrap gap-2">
              {SENSORS.map(s => (
                <Chip key={s.id} active={sensorId === s.id} onClick={() => { setSensorId(s.id); setColRanges({}); }} color="#3b82f6">
                  {s.label}
                </Chip>
              ))}
            </div>
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {numCols.map(col => (
                <RangeInput
                  key={col}
                  label={col.replace(/_/g, " ")}
                  min={colRanges[col]?.min ?? ""}
                  max={colRanges[col]?.max ?? ""}
                  onMin={v => setColRange(col, "min", v)}
                  onMax={v => setColRange(col, "max", v)}
                />
              ))}
            </div>
          </div>
        )}

        {source === "anomaly" && (
          <div className="flex flex-col gap-4">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">Anomaly Filters</span>
            <div className="flex flex-wrap gap-4">
              {/* Signal */}
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-muted uppercase tracking-wider">Signal</span>
                <select
                  value={signalFilter}
                  onChange={e => { setSignalFilter(e.target.value); setPage(0); }}
                  className="bg-background border border-card-border rounded px-3 py-1.5 text-xs text-foreground focus:outline-none focus:border-accent-blue"
                >
                  <option value="all">All signals</option>
                  {ALL_SIGNALS.map(s => <option key={s} value={s}>{s}</option>)}
                </select>
              </div>
              {/* Severity chips */}
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-muted uppercase tracking-wider">Severity</span>
                <div className="flex gap-1.5">
                  {ANOMALY_SEVERITIES.map(sev => (
                    <Chip key={sev} active={anomalySev === sev} onClick={() => { setAnomalySev(sev); setPage(0); }}
                      color={sevColor[sev] ?? "#6b7280"}>
                      {sev === "all" ? "All" : sev.charAt(0).toUpperCase() + sev.slice(1)}
                    </Chip>
                  ))}
                </div>
              </div>
              {/* Z-score range */}
              <RangeInput label="Z-score (abs)" min={zMin} max={zMax}
                onMin={v => { setZMin(v); setPage(0); }} onMax={v => { setZMax(v); setPage(0); }} />
              {/* Sustained */}
              <div className="flex flex-col gap-1 justify-end">
                <label className="flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={sustainedOnly}
                    onChange={e => { setSustainedOnly(e.target.checked); setPage(0); }}
                    className="accent-accent-purple w-3.5 h-3.5"
                  />
                  <span className="text-xs text-muted">Sustained only</span>
                </label>
              </div>
            </div>
          </div>
        )}

        {source === "alert" && (
          <div className="flex flex-col gap-4">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">Alert Filters</span>
            <div className="flex flex-wrap gap-4">
              {/* Severity chips */}
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-muted uppercase tracking-wider">Severity</span>
                <div className="flex gap-1.5">
                  {ALERT_SEVERITIES.map(sev => (
                    <Chip key={sev} active={alertSev === sev} onClick={() => { setAlertSev(sev); setPage(0); }}
                      color={sevColor[sev] ?? "#6b7280"}>
                      {sev === "all" ? "All" : sev.charAt(0).toUpperCase() + sev.slice(1)}
                    </Chip>
                  ))}
                </div>
              </div>
              {/* Rule dropdown */}
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-muted uppercase tracking-wider">Rule</span>
                <select
                  value={ruleFilter}
                  onChange={e => { setRuleFilter(e.target.value); setPage(0); }}
                  className="bg-background border border-card-border rounded px-3 py-1.5 text-xs text-foreground focus:outline-none focus:border-accent-blue"
                >
                  {uniqueRules.map(r => <option key={r} value={r}>{r === "all" ? "All rules" : r}</option>)}
                </select>
              </div>
              {/* Topic search */}
              <div className="flex flex-col gap-1">
                <span className="text-[10px] text-muted uppercase tracking-wider">Topic contains</span>
                <input
                  type="text"
                  placeholder="Search topic…"
                  value={topicSearch}
                  onChange={e => { setTopicSearch(e.target.value); setPage(0); }}
                  className="bg-background border border-card-border rounded px-3 py-1.5 text-xs text-foreground placeholder:text-muted focus:outline-none focus:border-accent-blue w-48"
                />
              </div>
            </div>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-between pt-1">
          <button
            onClick={() => { clearFilters(); }}
            className="text-xs text-muted hover:text-foreground transition-colors"
          >
            Clear all filters
          </button>
          <button
            onClick={fetchRecords}
            disabled={loading}
            className="flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-semibold bg-accent-blue text-white hover:opacity-90 disabled:opacity-50 transition-all"
          >
            {loading ? (
              <>
                <div className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Fetching…
              </>
            ) : (
              <>
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                </svg>
                Fetch Records
              </>
            )}
          </button>
        </div>
      </div>

      {/* Error */}
      {fetchError && (
        <div className="bg-accent-red/10 border border-accent-red/30 rounded-xl px-4 py-3 text-sm text-accent-red">
          Error: {fetchError}
        </div>
      )}

      {/* Stats bar + export */}
      {hasFetched && !loading && (
        <div className="bg-card border border-card-border rounded-xl px-4 py-3 flex flex-wrap items-center gap-3">
          {stats && (
            <>
              <StatPill label="Records" value={stats.count.toLocaleString()} />
              {source === "sensor" && "avgPower" in stats && (
                <>
                  <StatPill label="Avg Power" value={`${Number(stats.avgPower).toFixed(1)} W`} />
                  <StatPill label="Min Power" value={`${Number(stats.minPower).toFixed(1)} W`} />
                  <StatPill label="Max Power" value={`${Number(stats.maxPower).toFixed(1)} W`} />
                </>
              )}
              {source === "anomaly" && "avgZ" in stats && (
                <>
                  <StatPill label="Avg |Z|" value={Number(stats.avgZ).toFixed(2)} />
                  <StatPill label="Max |Z|" value={Number(stats.maxZ).toFixed(2)} />
                  <StatPill label="Critical" value={String(stats.critical)} />
                </>
              )}
              {source === "alert" && "warning" in stats && (
                <>
                  <StatPill label="Critical" value={String(stats.critical)} />
                  <StatPill label="Warning"  value={String(stats.warning)} />
                  <StatPill label="Info"     value={String(stats.info)} />
                </>
              )}
            </>
          )}
          <div className="ml-auto">
            <button
              onClick={() => exportCsv(sorted, exportFilename)}
              disabled={!sorted.length}
              className="flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-semibold border border-card-border text-muted hover:text-foreground hover:border-foreground/30 disabled:opacity-40 transition-all"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              Export CSV
            </button>
          </div>
        </div>
      )}

      {/* Table */}
      {hasFetched && !loading && (
        <div className="bg-card border border-card-border rounded-xl overflow-hidden">
          {sorted.length === 0 ? (
            <div className="py-16 text-center">
              <p className="text-muted text-sm">No records match the current filters.</p>
              <p className="text-[10px] text-muted mt-1">Try widening the time range or relaxing filter values.</p>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-left">
                  <thead>
                    <tr className="border-b border-card-border bg-background/40">
                      {columns.map(col => (
                        <th
                          key={col}
                          onClick={() => handleSort(col)}
                          className="px-3 py-2.5 text-[9px] font-semibold uppercase tracking-wider text-muted cursor-pointer select-none hover:text-foreground whitespace-nowrap group"
                        >
                          <span className="flex items-center gap-1">
                            {col.replace(/_/g, " ")}
                            <span className={`transition-opacity ${sortCol === col ? "opacity-100" : "opacity-0 group-hover:opacity-40"}`}>
                              {sortCol === col ? (sortDir === "asc" ? "↑" : "↓") : "↕"}
                            </span>
                          </span>
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {paged.map((row, i) => (
                      <tr key={i} className="border-b border-card-border hover:bg-background/40 transition-colors">
                        {columns.map(col => {
                          const val = row[col];
                          const isTs = col === "timestamp";
                          const isSev = col === "severity";
                          const isNum = typeof val === "number";

                          if (isSev && typeof val === "string") {
                            const color = sevColor[val] ?? "#6b7280";
                            return (
                              <td key={col} className="px-3 py-2">
                                <span
                                  className="text-[9px] font-bold uppercase px-1.5 py-0.5 rounded border"
                                  style={{ color, borderColor: `${color}40`, backgroundColor: `${color}15` }}
                                >
                                  {val}
                                </span>
                              </td>
                            );
                          }

                          return (
                            <td key={col} className="px-3 py-2 text-[10px] font-mono whitespace-nowrap">
                              {isTs
                                ? <span className="text-muted">{fmtTs(String(val ?? ""))}</span>
                                : isNum
                                  ? <span className="text-foreground">{fmtNum(val)}</span>
                                  : <span className="text-foreground">{val === null || val === undefined ? "—" : String(val)}</span>
                              }
                            </td>
                          );
                        })}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              {/* Pagination */}
              {totalPages > 1 && (
                <div className="flex items-center justify-between px-4 py-3 border-t border-card-border">
                  <span className="text-[10px] text-muted">
                    {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sorted.length)} of {sorted.length.toLocaleString()} records
                  </span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => setPage(0)}
                      disabled={page === 0}
                      className="px-2 py-1 text-[10px] rounded border border-card-border text-muted hover:text-foreground disabled:opacity-30 transition-all"
                    >«</button>
                    <button
                      onClick={() => setPage(p => Math.max(0, p - 1))}
                      disabled={page === 0}
                      className="px-2 py-1 text-[10px] rounded border border-card-border text-muted hover:text-foreground disabled:opacity-30 transition-all"
                    >‹ Prev</button>
                    <span className="px-3 py-1 text-[10px] text-foreground font-mono">
                      {page + 1} / {totalPages}
                    </span>
                    <button
                      onClick={() => setPage(p => Math.min(totalPages - 1, p + 1))}
                      disabled={page >= totalPages - 1}
                      className="px-2 py-1 text-[10px] rounded border border-card-border text-muted hover:text-foreground disabled:opacity-30 transition-all"
                    >Next ›</button>
                    <button
                      onClick={() => setPage(totalPages - 1)}
                      disabled={page >= totalPages - 1}
                      className="px-2 py-1 text-[10px] rounded border border-card-border text-muted hover:text-foreground disabled:opacity-30 transition-all"
                    >»</button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}

      {/* Empty state before first fetch */}
      {!hasFetched && !loading && (
        <div className="bg-card border border-card-border rounded-xl py-20 text-center">
          <svg className="w-10 h-10 text-muted mx-auto mb-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.2}>
            <path d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <p className="text-muted text-sm font-medium">No data loaded yet</p>
          <p className="text-[11px] text-muted mt-1">Set your filters and click <span className="text-foreground font-semibold">Fetch Records</span> to load data.</p>
        </div>
      )}
    </div>
  );
}
