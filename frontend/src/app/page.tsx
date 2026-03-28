"use client";

import React, { useState } from "react";
import BatteryDashboard from "@/components/BatteryDashboard";
import ACMeterDashboard from "@/components/ACMeterDashboard";

type Tab = "battery" | "ac";

export default function Home() {
  const [tab, setTab] = useState<Tab>("battery");

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
                AC Meter
              </span>
            </button>
          </nav>

          {/* Clock */}
          <div className="text-xs text-muted font-mono">
            <Clock />
          </div>
        </div>
      </header>

      {/* Dashboard content */}
      <main className="flex-1 max-w-7xl mx-auto w-full px-6 py-6">
        {tab === "battery" ? <BatteryDashboard /> : <ACMeterDashboard />}
      </main>

      {/* Footer */}
      <footer className="border-t border-card-border py-3 text-center text-xs text-muted">
        Smart Grid Energy Management System &middot; Simulated Sensor Data
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
