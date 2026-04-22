"use client";

import React, { useEffect, useState } from "react";
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
  threshold: string;
  on_time: string;
  off_time: string;
  priority: "Critical" | "High" | "Normal" | "Low";
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";
const API_URL = WS_URL.replace(/^ws/, "http");

interface Props {
  loadGroup: string;
  label: string;
}

export default function LoadControlPanel({ loadGroup, label }: Props) {
  const { data, connected } = useWebSocket<ACPayload>(`${WS_URL}/ws/ac/${loadGroup}`);

  const [state, setState] = useState<ControlState>({
    relay: "OFF",
    threshold: "",
    on_time: "",
    off_time: "",
    priority: "Normal",
  });
  const [sending, setSending] = useState(false);

  // Initial fetch — populates all fields including text inputs
  useEffect(() => {
    fetch(`${API_URL}/control/${loadGroup}`)
      .then((r) => r.json())
      .then((data) =>
        setState((prev) => ({
          ...prev,
          relay:     data.relay     ?? prev.relay,
          threshold: data.threshold != null ? String(data.threshold) : "",
          on_time:   data.on_time   ?? "",
          off_time:  data.off_time  ?? "",
          priority:  data.priority  ?? prev.priority,
        }))
      )
      .catch(() => {});
  }, [loadGroup]);

  // Recurring poll — only syncs instant-action fields (relay, priority).
  // Text inputs (threshold, on_time, off_time) are excluded so typing isn't interrupted.
  useEffect(() => {
    const id = setInterval(() => {
      fetch(`${API_URL}/control/${loadGroup}`)
        .then((r) => r.json())
        .then((data) =>
          setState((prev) => ({
            ...prev,
            relay:    data.relay    ?? prev.relay,
            priority: data.priority ?? prev.priority,
          }))
        )
        .catch(() => {});
    }, 1000);
    return () => clearInterval(id);
  }, [loadGroup]);

  async function sendControl(update: Record<string, unknown>) {
    setSending(true);
    try {
      const res = await fetch(`${API_URL}/control/${loadGroup}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(update),
      });
      if (res.ok) {
        setState((prev) => ({ ...prev, ...update }));
      }
    } catch {
      // silently fail — connection badge shows status
    } finally {
      setSending(false);
    }
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

      {/* Control cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">

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

        {/* Power threshold */}
        <ControlCard
          title="Power Threshold"
          description="Auto-trip the relay if power exceeds this limit. Leave blank to disable."
        >
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const val = state.threshold.trim();
              sendControl({ threshold: val === "" ? undefined : Number(val) });
            }}
            className="flex items-center gap-2"
          >
            <input
              type="number"
              min={0}
              placeholder="e.g. 3000"
              value={state.threshold}
              onChange={(e) => setState((p) => ({ ...p, threshold: e.target.value }))}
              className="flex-1 px-3 py-2 bg-background border border-card-border rounded-lg text-sm focus:outline-none focus:border-accent-amber"
            />
            <span className="text-xs text-muted">W</span>
            <button
              type="submit"
              className="px-3 py-2 text-xs font-semibold rounded-lg bg-accent-amber/15 text-accent-amber hover:bg-accent-amber/25 transition-colors"
            >
              Set
            </button>
          </form>
        </ControlCard>

        {/* Scheduled control */}
        <ControlCard
          title="Scheduled On/Off"
          description="Set a daily schedule for automatic load switching."
        >
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[10px] text-muted uppercase tracking-wider">On Time</label>
              <input
                type="time"
                value={state.on_time}
                onChange={(e) => setState((p) => ({ ...p, on_time: e.target.value }))}
                onBlur={() => sendControl({ on_time: state.on_time || undefined })}
                className="w-full px-3 py-2 bg-background border border-card-border rounded-lg text-sm focus:outline-none focus:border-accent-amber"
              />
            </div>
            <div>
              <label className="text-[10px] text-muted uppercase tracking-wider">Off Time</label>
              <input
                type="time"
                value={state.off_time}
                onChange={(e) => setState((p) => ({ ...p, off_time: e.target.value }))}
                onBlur={() => sendControl({ off_time: state.off_time || undefined })}
                className="w-full px-3 py-2 bg-background border border-card-border rounded-lg text-sm focus:outline-none focus:border-accent-amber"
              />
            </div>
          </div>
        </ControlCard>

        {/* Priority level */}
        <ControlCard
          title="Load Priority"
          description="Set the priority for load shedding. Lower priority loads are shed first."
        >
          <div className="flex gap-2">
            {(["Critical", "High", "Normal", "Low"] as const).map((level) => {
              const active = state.priority === level;
              return (
                <button
                  key={level}
                  onClick={() => sendControl({ priority: level })}
                  className={`flex-1 px-2 py-1.5 text-xs font-medium rounded-lg border transition-colors ${
                    active
                      ? "border-accent-amber bg-accent-amber/15 text-accent-amber"
                      : "border-card-border text-muted hover:border-accent-amber/40 hover:text-foreground"
                  }`}
                >
                  {level}
                </button>
              );
            })}
          </div>
        </ControlCard>
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

// --- Sub-components ---

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
