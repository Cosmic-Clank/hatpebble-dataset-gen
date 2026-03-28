"use client";

import React from "react";
import { useWebSocket } from "@/hooks/useWebSocket";
import Gauge from "./Gauge";
import RealtimeChart from "./RealtimeChart";
import StatCard from "./StatCard";
import ConnectionBadge from "./ConnectionBadge";

interface ACPayload {
  date: string;
  time: string;
  ac_voltage: number;
  ac_current: number;
  active_power: number;
  active_energy: number;
  frequency: number;
  power_factor: number;
}

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

export default function ACMeterDashboard() {
  const { data, history, connected } = useWebSocket<ACPayload>(`${WS_URL}/ws/ac`);

  const chartData = history.map((d, i) => ({
    idx: i,
    voltage: d.ac_voltage,
    current: d.ac_current,
    power: d.active_power,
    frequency: d.frequency,
    pf: d.power_factor,
  }));

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 rounded-lg bg-accent-blue/20 flex items-center justify-center">
            <svg className="w-5 h-5 text-accent-blue" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
            </svg>
          </div>
          <div>
            <h2 className="text-lg font-bold">PZEM-004T AC Multimeter</h2>
            <p className="text-xs text-muted">
              Phase 1 &middot; {data?.date ?? "—"} {data?.time ?? ""} &middot; Streaming at 1 Hz
            </p>
          </div>
        </div>
        <ConnectionBadge connected={connected} />
      </div>

      {/* Gauges */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <Gauge label="Voltage" value={data?.ac_voltage ?? null} min={200} max={260} unit="V" color="#3b82f6" decimals={1} />
        <Gauge label="Current" value={data?.ac_current ?? null} min={0} max={100} unit="A" color="#06b6d4" decimals={1} />
        <Gauge label="Active Power" value={data?.active_power ?? null} min={0} max={23000} unit="W" color="#f59e0b" decimals={0} />
        <Gauge label="Frequency" value={data?.frequency ?? null} min={49} max={51} unit="Hz" color="#a855f7" decimals={3} />
        <Gauge label="Power Factor" value={data?.power_factor ?? null} min={0} max={1} unit="PF" color="#22c55e" decimals={2} />
        <Gauge label="Energy" value={data?.active_energy ?? null} min={0} max={1} unit="kWh" color="#f97316" decimals={4} />
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <StatCard label="Voltage" value={data?.ac_voltage?.toFixed(1) ?? "—"} unit="V" color="#3b82f6" />
        <StatCard label="Current" value={data?.ac_current?.toFixed(1) ?? "—"} unit="A" color="#06b6d4" />
        <StatCard label="Power" value={data?.active_power?.toFixed(0) ?? "—"} unit="W" color="#f59e0b" />
        <StatCard label="Frequency" value={data?.frequency?.toFixed(3) ?? "—"} unit="Hz" color="#a855f7" />
        <StatCard label="PF" value={data?.power_factor?.toFixed(2) ?? "—"} unit="" color="#22c55e" />
        <StatCard label="Energy" value={data?.active_energy?.toFixed(4) ?? "—"} unit="kWh" color="#f97316" />
      </div>

      {/* Charts */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <RealtimeChart data={chartData} dataKey="voltage" xKey="idx" color="#3b82f6" label="AC Voltage" unit="V" decimals={1} />
        <RealtimeChart data={chartData} dataKey="current" xKey="idx" color="#06b6d4" label="AC Current" unit="A" decimals={1} />
        <RealtimeChart data={chartData} dataKey="power" xKey="idx" color="#f59e0b" label="Active Power" unit="W" decimals={0} />
        <RealtimeChart data={chartData} dataKey="frequency" xKey="idx" color="#a855f7" label="Frequency" unit="Hz" decimals={3} />
      </div>
    </div>
  );
}
