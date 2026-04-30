"use client";

import React, { useEffect, useState, useCallback } from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import ConnectionBadge from "./ConnectionBadge";

interface ACPayload {
  ac_voltage: number;
  ac_current: number;
  active_power: number;
  active_energy: number;
  frequency: number;
  power_factor: number;
}

interface ControlState {
  relay: "ON" | "OFF";
}

type ConditionType =
  | "time"
  | "power_above" | "power_below"
  | "voltage_above" | "voltage_below"
  | "current_above" | "current_below"
  | "frequency_above" | "frequency_below"
  | "pf_above" | "pf_below"
  | "soc_above" | "soc_below"
  | "bat_voltage_above" | "bat_voltage_below";

interface Rule {
  id: string;
  load_group: string;
  name: string;
  enabled: boolean;
  condition_type: ConditionType;
  condition_value: string;
  action: "ON" | "OFF";
  created_at: string;
}

interface NewRuleForm {
  name: string;
  condition_type: ConditionType;
  condition_value: string;
  action: "ON" | "OFF";
}

const WS_URL  = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
const API_URL = WS_URL.replace(/^ws/, "http");

const CONDITION_META: Record<ConditionType, { label: string; unit: string; placeholder: string; isTime: boolean }> = {
  time:              { label: "At time of day",           unit: "",    placeholder: "",       isTime: true  },
  power_above:       { label: "Power exceeds",            unit: "W",   placeholder: "3000",   isTime: false },
  power_below:       { label: "Power drops below",        unit: "W",   placeholder: "500",    isTime: false },
  voltage_above:     { label: "AC voltage exceeds",       unit: "V",   placeholder: "240",    isTime: false },
  voltage_below:     { label: "AC voltage drops below",   unit: "V",   placeholder: "210",    isTime: false },
  current_above:     { label: "Current exceeds",          unit: "A",   placeholder: "15",     isTime: false },
  current_below:     { label: "Current drops below",      unit: "A",   placeholder: "1",      isTime: false },
  frequency_above:   { label: "Frequency exceeds",        unit: "Hz",  placeholder: "51",     isTime: false },
  frequency_below:   { label: "Frequency drops below",   unit: "Hz",  placeholder: "49",     isTime: false },
  pf_above:          { label: "Power factor exceeds",     unit: "",    placeholder: "0.95",   isTime: false },
  pf_below:          { label: "Power factor drops below", unit: "",    placeholder: "0.8",    isTime: false },
  soc_above:         { label: "Battery SOC exceeds",      unit: "%",   placeholder: "90",     isTime: false },
  soc_below:         { label: "Battery SOC drops below",  unit: "%",   placeholder: "20",     isTime: false },
  bat_voltage_above: { label: "Battery voltage exceeds",  unit: "V",   placeholder: "14",     isTime: false },
  bat_voltage_below: { label: "Battery voltage drops below", unit: "V", placeholder: "11.5", isTime: false },
};

interface Props {
  loadGroup: string;
  label: string;
}

export default function LoadControlPanel({ loadGroup, label }: Props) {
  const { data, connected } = useWebSocket<ACPayload>(`${WS_URL}/ws/ac/${loadGroup}`);

  const [state, setState] = useState<ControlState>({ relay: "OFF" });
  const [sending, setSending] = useState(false);

  // ── Rules state ──────────────────────────────────────────────────────────
  const [rules,    setRules]    = useState<Rule[]>([]);
  const [addOpen,  setAddOpen]  = useState(false);
  const [saving,   setSaving]   = useState(false);
  const [newRule,  setNewRule]  = useState<NewRuleForm>({
    name: "",
    condition_type: "power_above",
    condition_value: "",
    action: "OFF",
  });

  // Poll relay state
  useEffect(() => {
    const sync = () =>
      fetch(`${API_URL}/control/${loadGroup}`)
        .then((r) => r.json())
        .then((data) => setState((prev) => ({ ...prev, relay: data.relay ?? prev.relay })))
        .catch(() => {});
    sync();
    const id = setInterval(sync, 1000);
    return () => clearInterval(id);
  }, [loadGroup]);

  // Fetch rules for this load group
  const fetchRules = useCallback(() => {
    fetch(`${API_URL}/api/rules?load_group=${loadGroup}`)
      .then((r) => r.json())
      .then((data: Rule[]) => setRules(data))
      .catch(() => {});
  }, [loadGroup]);

  useEffect(() => {
    fetchRules();
  }, [fetchRules]);

  async function sendControl(update: Record<string, unknown>) {
    setSending(true);
    try {
      const res = await fetch(`${API_URL}/control/${loadGroup}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });
      if (res.ok) setState((prev) => ({ ...prev, ...update }));
    } catch {
      // silently fail — connection badge shows status
    } finally {
      setSending(false);
    }
  }

  async function handleAddRule(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!newRule.condition_value.trim()) return;
    setSaving(true);
    try {
      const res = await fetch(`${API_URL}/api/rules`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ load_group: loadGroup, ...newRule }),
      });
      if (res.ok) {
        setAddOpen(false);
        setNewRule({ name: "", condition_type: "power_above", condition_value: "", action: "OFF" });
        fetchRules();
      }
    } catch {
      // noop
    } finally {
      setSaving(false);
    }
  }

  async function handleDeleteRule(id: string) {
    await fetch(`${API_URL}/api/rules/${id}`, { method: "DELETE" }).catch(() => {});
    fetchRules();
  }

  async function handleToggleRule(id: string, enabled: boolean) {
    await fetch(`${API_URL}/api/rules/${id}/enabled`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    }).catch(() => {});
    fetchRules();
  }

  const relayOn = state.relay === "ON";

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-accent-amber/15 flex items-center justify-center">
            <svg className="w-5 h-5 text-accent-amber" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
            </svg>
          </div>
          <div>
            <h2 className="text-lg font-bold">{label} — Controls</h2>
            <p className="text-xs text-muted">Load management &middot; Elevated access</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {sending && (
            <span className="text-[10px] text-accent-amber animate-pulse font-medium">Sending…</span>
          )}
          <ConnectionBadge connected={connected} />
        </div>
      </div>

      {/* Live status strip */}
      <div className="bg-card border border-card-border rounded-xl p-4">
        <div className="text-[10px] font-semibold uppercase tracking-widest text-muted/70 mb-3">
          Live Readings
        </div>
        <div className="grid grid-cols-3 md:grid-cols-6 gap-4">
          <LiveStat label="Voltage"   value={data?.ac_voltage?.toFixed(1)}    unit="V"   />
          <LiveStat label="Current"   value={data?.ac_current?.toFixed(2)}    unit="A"   />
          <LiveStat label="Power"     value={data?.active_power?.toFixed(0)}  unit="W"   />
          <LiveStat label="Energy"    value={data?.active_energy?.toFixed(3)} unit="kWh" />
          <LiveStat label="Frequency" value={data?.frequency?.toFixed(2)}     unit="Hz"  />
          <LiveStat label="PF"        value={data?.power_factor?.toFixed(2)}  unit=""    />
        </div>
      </div>

      {/* Relay toggle */}
      <ControlCard title="Relay Switch" description="Toggle the load circuit on or off.">
        <div className="flex items-center justify-between">
          <div>
            <span className="text-sm text-foreground">Circuit Power</span>
            <p className="text-[10px] text-muted mt-0.5">
              {relayOn ? "Circuit is energised" : "Circuit is open"}
            </p>
          </div>
          <button
            onClick={() => sendControl({ relay: relayOn ? "OFF" : "ON" })}
            className={`relative w-11 h-6 rounded-full transition-colors duration-200 focus:outline-none ${
              relayOn ? "bg-accent-green" : "bg-muted/30"
            }`}
          >
            <span
              className={`absolute top-1 left-1 w-4 h-4 rounded-full bg-white shadow transition-transform duration-200 ${
                relayOn ? "translate-x-5" : "translate-x-0"
              }`}
            />
          </button>
        </div>
      </ControlCard>

      {/* ── Automation Rules ────────────────────────────────────────────── */}
      <div className="bg-card border border-card-border rounded-xl p-5 flex flex-col gap-4">
        {/* Section header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <svg className="w-4 h-4 text-accent-amber" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
            <h3 className="text-sm font-semibold">Automation Rules</h3>
            {rules.length > 0 && (
              <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-accent-amber/15 text-accent-amber">
                {rules.length}
              </span>
            )}
          </div>
          <button
            onClick={() => setAddOpen((v) => !v)}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg
                       bg-accent-amber/10 text-accent-amber hover:bg-accent-amber/20 transition-colors"
          >
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
              <path d="M12 4v16m-8-8h16" />
            </svg>
            Add Rule
          </button>
        </div>

        <p className="text-xs text-muted -mt-2">
          Rules run every 5 s. Time rules fire once per day; threshold rules (power, voltage, current, frequency, SOC) re-arm after 60 s.
        </p>

        {/* Add rule form */}
        {addOpen && (
          <form
            onSubmit={handleAddRule}
            className="border border-accent-amber/30 bg-accent-amber/5 rounded-xl p-4 flex flex-col gap-3"
          >
            <p className="text-xs font-semibold text-accent-amber uppercase tracking-wider">New Rule</p>

            {/* Name */}
            <div>
              <label className="text-[10px] text-muted uppercase tracking-wider">Rule Name</label>
              <input
                type="text"
                placeholder="e.g. Peak hours off"
                value={newRule.name}
                onChange={(e) => setNewRule((p) => ({ ...p, name: e.target.value }))}
                className="w-full mt-1 px-3 py-2 bg-background border border-card-border rounded-lg text-sm focus:outline-none focus:border-accent-amber"
              />
            </div>

            {/* Condition type + value */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-[10px] text-muted uppercase tracking-wider">Condition</label>
                <select
                  value={newRule.condition_type}
                  onChange={(e) =>
                    setNewRule((p) => ({
                      ...p,
                      condition_type: e.target.value as ConditionType,
                      condition_value: "",
                    }))
                  }
                  className="w-full mt-1 px-3 py-2 bg-background border border-card-border rounded-lg text-sm focus:outline-none focus:border-accent-amber"
                >
                  <optgroup label="Time">
                    <option value="time">At time of day</option>
                  </optgroup>
                  <optgroup label="AC Load">
                    <option value="power_above">Power exceeds (W)</option>
                    <option value="power_below">Power drops below (W)</option>
                    <option value="voltage_above">AC voltage exceeds (V)</option>
                    <option value="voltage_below">AC voltage drops below (V)</option>
                    <option value="current_above">Current exceeds (A)</option>
                    <option value="current_below">Current drops below (A)</option>
                    <option value="frequency_above">Frequency exceeds (Hz)</option>
                    <option value="frequency_below">Frequency drops below (Hz)</option>
                    <option value="pf_above">Power factor exceeds</option>
                    <option value="pf_below">Power factor drops below</option>
                  </optgroup>
                  <optgroup label="Battery">
                    <option value="soc_above">Battery SOC exceeds (%)</option>
                    <option value="soc_below">Battery SOC drops below (%)</option>
                    <option value="bat_voltage_above">Battery voltage exceeds (V)</option>
                    <option value="bat_voltage_below">Battery voltage drops below (V)</option>
                  </optgroup>
                </select>
              </div>
              <div>
                {(() => {
                  const meta = CONDITION_META[newRule.condition_type];
                  return (
                    <>
                      <label className="text-[10px] text-muted uppercase tracking-wider">
                        {meta.isTime ? "Time (HH:MM)" : `Threshold${meta.unit ? ` (${meta.unit})` : ""}`}
                      </label>
                      {meta.isTime ? (
                        <input
                          type="time"
                          required
                          value={newRule.condition_value}
                          onChange={(e) => setNewRule((p) => ({ ...p, condition_value: e.target.value }))}
                          className="w-full mt-1 px-3 py-2 bg-background border border-card-border rounded-lg text-sm focus:outline-none focus:border-accent-amber"
                        />
                      ) : (
                        <input
                          type="number"
                          required
                          min={0}
                          step="any"
                          placeholder={meta.placeholder}
                          value={newRule.condition_value}
                          onChange={(e) => setNewRule((p) => ({ ...p, condition_value: e.target.value }))}
                          className="w-full mt-1 px-3 py-2 bg-background border border-card-border rounded-lg text-sm focus:outline-none focus:border-accent-amber"
                        />
                      )}
                    </>
                  );
                })()}
              </div>
            </div>

            {/* Action */}
            <div>
              <label className="text-[10px] text-muted uppercase tracking-wider">Action</label>
              <div className="flex gap-2 mt-1">
                {(["ON", "OFF"] as const).map((a) => (
                  <button
                    type="button"
                    key={a}
                    onClick={() => setNewRule((p) => ({ ...p, action: a }))}
                    className={`flex-1 py-2 text-xs font-semibold rounded-lg border transition-colors ${
                      newRule.action === a
                        ? a === "ON"
                          ? "border-accent-green bg-accent-green/15 text-accent-green"
                          : "border-accent-red bg-accent-red/15 text-accent-red"
                        : "border-card-border text-muted hover:text-foreground"
                    }`}
                  >
                    Turn {a}
                  </button>
                ))}
              </div>
            </div>

            {/* Submit / Cancel */}
            <div className="flex gap-2 pt-1">
              <button
                type="submit"
                disabled={saving || !newRule.condition_value.trim()}
                className="flex-1 py-2 text-xs font-semibold rounded-lg bg-accent-amber text-white
                           hover:opacity-90 disabled:opacity-40 transition-all"
              >
                {saving ? "Saving…" : "Save Rule"}
              </button>
              <button
                type="button"
                onClick={() => { setAddOpen(false); setNewRule({ name: "", condition_type: "power_above", condition_value: "", action: "OFF" }); }}
                className="px-4 py-2 text-xs font-medium rounded-lg border border-card-border text-muted hover:text-foreground transition-colors"
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {/* Rules list */}
        {rules.length === 0 && !addOpen ? (
          <div className="text-center py-6 text-xs text-muted border border-dashed border-card-border rounded-xl">
            No automation rules yet. Click <strong>Add Rule</strong> to create one.
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            {rules.map((rule) => (
              <RuleRow
                key={rule.id}
                rule={rule}
                onToggle={(enabled) => handleToggleRule(rule.id, enabled)}
                onDelete={() => handleDeleteRule(rule.id)}
              />
            ))}
          </div>
        )}
      </div>

      {/* Status banner */}
      <div className={`border rounded-xl p-4 text-sm ${
        connected
          ? "bg-accent-green/5 border-accent-green/20 text-accent-green/80"
          : "bg-muted/5 border-dashed border-muted/20 text-muted"
      }`}>
        {connected
          ? <>Commands publish to <code className="text-xs bg-background px-1.5 py-0.5 rounded">ems/control/{loadGroup}</code> via MQTT.</>
          : "WebSocket disconnected — commands will fail until the backend reconnects."}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Rule row
// ---------------------------------------------------------------------------

function RuleRow({
  rule,
  onToggle,
  onDelete,
}: {
  rule: Rule;
  onToggle: (enabled: boolean) => void;
  onDelete: () => void;
}) {
  const meta = CONDITION_META[rule.condition_type];
  const isAbove = rule.condition_type.endsWith("_above");
  const conditionLabel = meta.isTime
    ? `At ${rule.condition_value}`
    : `${meta.label.replace(" exceeds", "").replace(" drops below", "")} ${isAbove ? ">" : "<"} ${rule.condition_value}${meta.unit ? ` ${meta.unit}` : ""}`;

  const conditionIcon =
    rule.condition_type === "time" ? (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" />
      </svg>
    ) : rule.condition_type.startsWith("soc") || rule.condition_type.startsWith("bat_") ? (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <rect x="2" y="7" width="16" height="10" rx="2" /><path d="M22 11v2" />
      </svg>
    ) : rule.condition_type.startsWith("frequency") ? (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path d="M2 12h3l3-7 4 14 3-7h3" />
      </svg>
    ) : rule.condition_type.startsWith("voltage") ? (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    ) : (
      <svg className="w-3.5 h-3.5 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path d="M13 10V3L4 14h7v7l9-11h-7z" />
      </svg>
    );

  return (
    <div
      className={`flex items-center gap-3 px-4 py-3 rounded-xl border transition-all ${
        rule.enabled
          ? "border-card-border bg-background/50"
          : "border-dashed border-card-border/50 opacity-50"
      }`}
    >
      {/* Condition icon */}
      <span className="text-muted">{conditionIcon}</span>

      {/* Text */}
      <div className="flex-1 min-w-0">
        <p className="text-xs font-semibold text-foreground truncate">{rule.name || conditionLabel}</p>
        <p className="text-[10px] text-muted mt-0.5 truncate">{conditionLabel}</p>
      </div>

      {/* Action badge */}
      <span
        className={`text-[10px] font-bold px-2 py-0.5 rounded border shrink-0 ${
          rule.action === "ON"
            ? "text-accent-green border-accent-green/30 bg-accent-green/10"
            : "text-accent-red border-accent-red/30 bg-accent-red/10"
        }`}
      >
        → {rule.action}
      </span>

      {/* Enable toggle */}
      <button
        onClick={() => onToggle(!rule.enabled)}
        className={`relative w-9 h-5 rounded-full transition-colors shrink-0 focus:outline-none ${
          rule.enabled ? "bg-accent-green" : "bg-muted/30"
        }`}
        title={rule.enabled ? "Disable rule" : "Enable rule"}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow transition-transform ${
            rule.enabled ? "translate-x-4" : "translate-x-0"
          }`}
        />
      </button>

      {/* Delete */}
      <button
        onClick={onDelete}
        className="text-muted hover:text-accent-red transition-colors shrink-0 p-1 rounded"
        title="Delete rule"
      >
        <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
        </svg>
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ControlCard({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-card border border-card-border rounded-xl p-5 space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground mb-1">{title}</h3>
        <p className="text-xs text-muted">{description}</p>
      </div>
      <div>{children}</div>
    </div>
  );
}

function LiveStat({ label, value, unit }: { label: string; value: string | undefined; unit: string }) {
  return (
    <div>
      <p className="text-[10px] text-muted uppercase tracking-wider">{label}</p>
      <p className="text-sm font-mono font-semibold text-foreground">
        {value ?? "—"}
        <span className="text-[10px] text-muted ml-0.5 font-sans font-normal">{unit}</span>
      </p>
    </div>
  );
}
