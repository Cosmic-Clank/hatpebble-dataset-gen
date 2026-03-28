"use client";

import React from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import Gauge from "./Gauge";
import RealtimeChart from "./RealtimeChart";
import StatCard from "./StatCard";
import ConnectionBadge from "./ConnectionBadge";

interface BatteryPayload {
  time: number;
  battery_voltage: number;
  battery_current: number;
  battery_power: number;
  soc: number | null;
  consumed_ah: number | null;
  time_to_go: number | null;
  alarm_flags: number | null;
  temperature: number | null;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

export default function BatteryDashboard() {
  const { data, history, connected } = useWebSocket<BatteryPayload>(`${WS_URL}/ws/battery`);

  const chartData = history.map((d, i) => ({
    idx: i,
    voltage: d.battery_voltage,
    current: d.battery_current,
    power: d.battery_power,
    temperature: d.temperature ?? 0,
  }));

  const isCharging = (data?.battery_current ?? 0) < 0;

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-accent-green/20 flex items-center justify-center">
            <svg className="w-5 h-5 text-accent-green" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <rect x="6" y="4" width="12" height="18" rx="2" />
              <rect x="9" y="1" width="6" height="3" rx="1" />
              <path d="M10 14l2-3 2 3" />
            </svg>
          </div>
          <div>
            <h2 className="text-lg font-bold">Victron SmartShunt Battery Monitor</h2>
            <p className="text-xs text-muted">
              {isCharging ? "Charging" : "Discharging"} &middot; Streaming at 1 Hz
            </p>
          </div>
        </div>
        <ConnectionBadge connected={connected} />
      </div>

      {/* Gauges */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Gauge label="Voltage" value={data?.battery_voltage ?? null} min={2.5} max={4.2} unit="V" color="#22c55e" />
        <Gauge label="Current" value={data?.battery_current ?? null} min={-25} max={25} unit="A" color="#3b82f6" />
        <Gauge label="Power" value={data?.battery_power ?? null} min={-80} max={80} unit="W" color="#f59e0b" />
        <Gauge label="Temperature" value={data?.temperature ?? null} min={15} max={50} unit="°C" color="#ef4444" decimals={1} />
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="SoC" value={data?.soc != null ? `${data.soc.toFixed(1)}` : "N/A"} unit="%" color="#22c55e" />
        <StatCard label="Consumed Ah" value={data?.consumed_ah != null ? data.consumed_ah.toFixed(2) : "N/A"} unit="Ah" color="#3b82f6" />
        <StatCard label="Time-to-Go" value={data?.time_to_go != null ? data.time_to_go.toFixed(1) : "N/A"} unit="h" color="#a855f7" />
        <StatCard label="Alarm Flags" value={data?.alarm_flags ?? "None"} unit="" color="#64748b" />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <RealtimeChart data={chartData} dataKey="voltage" xKey="idx" color="#22c55e" label="Voltage" unit="V" decimals={3} />
        <RealtimeChart data={chartData} dataKey="current" xKey="idx" color="#3b82f6" label="Current" unit="A" />
        <RealtimeChart data={chartData} dataKey="power" xKey="idx" color="#f59e0b" label="Power" unit="W" decimals={1} />
        <RealtimeChart data={chartData} dataKey="temperature" xKey="idx" color="#ef4444" label="Temperature" unit="°C" decimals={1} />
      </div>
    </div>
  );
}
