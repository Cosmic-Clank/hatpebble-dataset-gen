"use client";

import React, { useState } from "react";
import BatteryDashboard from "@/components/BatteryDashboard";
import ACMeterDashboard from "@/components/ACMeterDashboard";
import { useAuth } from "@/lib/auth-context";

type Tab = "battery" | "ac" | "controls";

const LOAD_GROUPS = [
  { id: "load1", label: "Load Group 1 — Main Circuit" },
  { id: "load2", label: "Load Group 2 — HVAC System" },
  { id: "load3", label: "Load Group 3 — Water Heater" },
] as const;

export default function Home() {
  const { user, role, loading, signOut } = useAuth();
  const [tab, setTab] = useState<Tab>("battery");
  const [activeLoad, setActiveLoad] = useState<string>("load1");

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="text-muted text-sm">Loading...</div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex flex-col bg-background text-foreground">
      {/* Top bar */}
      <header className="border-b border-card-border bg-card/80 backdrop-blur-sm sticky top-0 z-50">
        <div className="max-w-7xl mx-auto px-6 h-14 flex items-center justify-between">
          {/* Logo / title */}
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent-green to-accent-blue flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <span className="font-bold text-lg tracking-tight">Smart Grid EMS</span>
          </div>

          {/* Tab nav */}
          <nav className="flex gap-1 bg-background/50 rounded-lg p-1">
            <button
              onClick={() => setTab("battery")}
              className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                tab === "battery"
                  ? "bg-accent-green/20 text-accent-green shadow-sm"
                  : "text-muted hover:text-foreground"
              }`}
            >
              <span className="flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <rect x="6" y="4" width="12" height="18" rx="2" />
                  <rect x="9" y="1" width="6" height="3" rx="1" />
                </svg>
                Battery
              </span>
            </button>
            <button
              onClick={() => setTab("ac")}
              className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                tab === "ac"
                  ? "bg-accent-blue/20 text-accent-blue shadow-sm"
                  : "text-muted hover:text-foreground"
              }`}
            >
              <span className="flex items-center gap-2">
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
                </svg>
                AC Loads
              </span>
            </button>
            {role === "elevated" && (
              <button
                onClick={() => setTab("controls")}
                className={`px-4 py-1.5 text-sm font-medium rounded-md transition-all ${
                  tab === "controls"
                    ? "bg-accent-amber/20 text-accent-amber shadow-sm"
                    : "text-muted hover:text-foreground"
                }`}
              >
                <span className="flex items-center gap-2">
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
                  </svg>
                  Controls
                </span>
              </button>
            )}
          </nav>

          {/* User info + clock */}
          <div className="flex items-center gap-4">
            <div className="flex items-center gap-2">
              <span
                className={`px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-full ${
                  role === "elevated"
                    ? "bg-accent-amber/20 text-accent-amber"
                    : "bg-accent-blue/20 text-accent-blue"
                }`}
              >
                {role}
              </span>
              <span className="text-xs text-muted truncate max-w-35">
                {user?.email}
              </span>
            </div>
            <button
              onClick={signOut}
              className="text-xs text-muted hover:text-accent-red transition-colors"
            >
              Sign out
            </button>
            <div className="text-xs text-muted font-mono border-l border-card-border pl-4">
              <Clock />
            </div>
          </div>
        </div>
      </header>

      {/* Load group sub-tabs (shown when AC tab is active) */}
      {tab === "ac" && (
        <div className="border-b border-card-border bg-card/40">
          <div className="max-w-7xl mx-auto px-6 flex gap-1 py-2">
            {LOAD_GROUPS.map((lg) => (
              <button
                key={lg.id}
                onClick={() => setActiveLoad(lg.id)}
                className={`px-3 py-1 text-xs font-medium rounded-md transition-all ${
                  activeLoad === lg.id
                    ? "bg-accent-blue/15 text-accent-blue"
                    : "text-muted hover:text-foreground"
                }`}
              >
                {lg.label}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Dashboard content */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-6">
        {tab === "battery" && <BatteryDashboard />}
        {tab === "ac" && (
          <ACMeterDashboard
            key={activeLoad}
            loadGroup={activeLoad}
            label={LOAD_GROUPS.find((lg) => lg.id === activeLoad)!.label}
          />
        )}
        {tab === "controls" && role === "elevated" && <ControlsPanel />}
      </main>

      {/* Footer */}
      <footer className="border-t border-card-border py-3 text-center text-xs text-muted">
        Smart Grid Energy Management System &middot; Live Sensor Data
      </footer>
    </div>
  );
}

function Clock() {
  const [time, setTime] = React.useState(new Date());
  React.useEffect(() => {
    const id = setInterval(() => setTime(new Date()), 1000);
    return () => clearInterval(id);
  }, []);
  return <>{time.toLocaleTimeString()}</>;
}

function ControlsPanel() {
  // TODO: Implement load control interface
  // This panel will allow elevated users to:
  // - Toggle loads on/off via ESP32 relay commands
  // - Set power thresholds and alerts
  // - Configure scheduled load shedding
  // - Override automatic load management
  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <h2 className="text-lg font-bold">Load Controls</h2>
        <span className="px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-full bg-accent-amber/20 text-accent-amber">
          Elevated Access
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {LOAD_GROUPS.map((lg) => (
          <div
            key={lg.id}
            className="bg-card border border-card-border rounded-xl p-5"
          >
            <div className="flex items-center justify-between mb-3">
              <span className="text-sm font-medium text-foreground">
                {lg.label}
              </span>
              <div className="w-10 h-5 rounded-full bg-muted/30 relative cursor-not-allowed">
                <div className="absolute left-0.5 top-0.5 w-4 h-4 rounded-full bg-muted/50 transition-transform" />
              </div>
            </div>
            <div className="text-xs text-muted">
              Control not connected — awaiting ESP32 relay module
            </div>
          </div>
        ))}
      </div>

      <div className="bg-card border border-dashed border-accent-amber/30 rounded-xl p-5">
        <p className="text-sm text-accent-amber/80">
          Load control requires ESP32 relay modules connected to the MQTT broker.
          Controls will become active once relay firmware is deployed and publishing to{" "}
          <code className="text-xs bg-background px-1.5 py-0.5 rounded">
            ems/control/#
          </code>{" "}
          topics.
        </p>
      </div>
    </div>
  );
}
