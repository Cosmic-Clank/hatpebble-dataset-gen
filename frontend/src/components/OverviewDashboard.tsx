"use client";

import React from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import ConnectionBadge from "./ConnectionBadge";

interface BatteryPayload {
  battery_voltage: number;
  battery_current: number;
  battery_power: number;
  soc: number | null;
  temperature: number | null;
}

interface ACPayload {
  ac_voltage: number;
  ac_current: number;
  active_power: number;
  active_energy: number;
  frequency: number;
  power_factor: number;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

const LOADS = [
  { id: "load1", label: "Load Group 1", color: "#3b82f6" },
  { id: "load2", label: "Load Group 2", color: "#8b5cf6" },
  { id: "load3", label: "Load Group 3", color: "#06b6d4" },
];

export default function OverviewDashboard() {
  const battery = useWebSocket<BatteryPayload>(`${WS_URL}/ws/battery`);
  const load1 = useWebSocket<ACPayload>(`${WS_URL}/ws/ac/load1`);
  const load2 = useWebSocket<ACPayload>(`${WS_URL}/ws/ac/load2`);
  const load3 = useWebSocket<ACPayload>(`${WS_URL}/ws/ac/load3`);

  const loads = [load1, load2, load3];
  const totalPower = loads.reduce((sum, l) => sum + (l.data?.active_power ?? 0), 0);
  const totalEnergy = loads.reduce((sum, l) => sum + (l.data?.active_energy ?? 0), 0);
  const allConnected = battery.connected && loads.every((l) => l.connected);
  const connectedCount = [battery, ...loads].filter((s) => s.connected).length;

  return (
    <div className="flex flex-col gap-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold">System Overview</h1>
          <p className="text-xs text-muted mt-0.5">
            Real-time summary of all connected sensors
          </p>
        </div>
        <div className="flex items-center gap-3">
          <span className="text-xs text-muted">
            {connectedCount}/4 sensors online
          </span>
          <ConnectionBadge connected={allConnected} />
        </div>
      </div>

      {/* Top stats row */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <SummaryCard
          label="Total AC Power"
          value={totalPower.toFixed(0)}
          unit="W"
          color="#f59e0b"
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
            </svg>
          }
        />
        <SummaryCard
          label="Total Energy"
          value={totalEnergy.toFixed(3)}
          unit="kWh"
          color="#f97316"
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <circle cx="12" cy="12" r="9" />
              <path d="M12 7v5l3 3" />
            </svg>
          }
        />
        <SummaryCard
          label="Battery SoC"
          value={battery.data?.soc?.toFixed(1) ?? "N/A"}
          unit="%"
          color="#22c55e"
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <rect x="6" y="4" width="12" height="18" rx="2" />
              <rect x="9" y="1" width="6" height="3" rx="1" />
            </svg>
          }
        />
        <SummaryCard
          label="Battery Power"
          value={battery.data?.battery_power?.toFixed(1) ?? "N/A"}
          unit="W"
          color="#3b82f6"
          icon={
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.8}>
              <path d="M12 3v18m-6-6l6 6 6-6" />
            </svg>
          }
        />
      </div>

      {/* Battery section */}
      <div className="bg-card border border-card-border rounded-xl p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-accent-green/15 flex items-center justify-center">
              <svg className="w-4 h-4 text-accent-green" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <rect x="6" y="4" width="12" height="18" rx="2" />
                <rect x="9" y="1" width="6" height="3" rx="1" />
              </svg>
            </div>
            <h2 className="text-sm font-semibold">Battery System</h2>
          </div>
          <ConnectionBadge connected={battery.connected} />
        </div>
        <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
          <MiniStat label="Voltage" value={battery.data?.battery_voltage?.toFixed(2)} unit="V" />
          <MiniStat label="Current" value={battery.data?.battery_current?.toFixed(2)} unit="A" />
          <MiniStat label="Power" value={battery.data?.battery_power?.toFixed(1)} unit="W" />
          <MiniStat label="SoC" value={battery.data?.soc?.toFixed(1)} unit="%" />
          <MiniStat label="Temperature" value={battery.data?.temperature?.toFixed(1)} unit="°C" />
        </div>
      </div>

      {/* Load groups grid */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {LOADS.map((load, i) => {
          const ws = loads[i];
          return (
            <div key={load.id} className="bg-card border border-card-border rounded-xl p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div
                    className="w-8 h-8 rounded-lg flex items-center justify-center"
                    style={{ backgroundColor: `${load.color}15` }}
                  >
                    <svg
                      className="w-4 h-4"
                      style={{ color: load.color }}
                      fill="none"
                      viewBox="0 0 24 24"
                      stroke="currentColor"
                      strokeWidth={2}
                    >
                      <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                    </svg>
                  </div>
                  <h3 className="text-sm font-semibold">{load.label}</h3>
                </div>
                <ConnectionBadge connected={ws.connected} />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <MiniStat label="Voltage" value={ws.data?.ac_voltage?.toFixed(1)} unit="V" />
                <MiniStat label="Current" value={ws.data?.ac_current?.toFixed(2)} unit="A" />
                <MiniStat label="Power" value={ws.data?.active_power?.toFixed(0)} unit="W" />
                <MiniStat label="PF" value={ws.data?.power_factor?.toFixed(2)} unit="" />
                <MiniStat label="Energy" value={ws.data?.active_energy?.toFixed(3)} unit="kWh" />
                <MiniStat label="Frequency" value={ws.data?.frequency?.toFixed(2)} unit="Hz" />
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// --- Sub-components ---

function SummaryCard({
  label,
  value,
  unit,
  color,
  icon,
}: {
  label: string;
  value: string;
  unit: string;
  color: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="bg-card border border-card-border rounded-xl p-4 flex items-start gap-3">
      <div
        className="w-10 h-10 rounded-lg flex items-center justify-center shrink-0"
        style={{ backgroundColor: `${color}15`, color }}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <p className="text-[10px] font-medium uppercase tracking-wider text-muted">{label}</p>
        <p className="text-lg font-bold font-mono" style={{ color }}>
          {value}
          <span className="text-xs text-muted ml-1 font-sans font-normal">{unit}</span>
        </p>
      </div>
    </div>
  );
}

function MiniStat({
  label,
  value,
  unit,
}: {
  label: string;
  value: string | undefined;
  unit: string;
}) {
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
