"use client";

import React, { useState } from "react";
import Sidebar, { type Page } from "@/components/Sidebar";
import OverviewDashboard from "@/components/OverviewDashboard";
import BatteryDashboard from "@/components/BatteryDashboard";
import ACMeterDashboard from "@/components/ACMeterDashboard";
import LoadControlPanel from "@/components/LoadControlPanel";
import AlertsFeed from "@/components/AlertsFeed";
import { useAuth } from "@/lib/auth-context";

export default function Home() {
  const { loading } = useAuth();
  const [page, setPage] = useState<Page>("overview");
  const [alertBadge, setAlertBadge] = useState(0);

  function handleNavigate(p: Page) {
    setPage(p);
    if (p === "alerts") setAlertBadge(0);
  }

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex items-center gap-3">
          <div className="w-5 h-5 border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
          <span className="text-muted text-sm">Loading dashboard...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen bg-background text-foreground">
      <Sidebar active={page} onNavigate={handleNavigate} alertBadge={alertBadge} />

      <div className="flex-1 flex flex-col min-h-screen">
        {/* Top bar */}
        <header className="h-14 border-b border-card-border bg-card/40 backdrop-blur-sm sticky top-0 z-40 flex items-center justify-between px-6">
          <PageTitle page={page} />
          <div className="text-xs text-muted font-mono">
            <Clock />
          </div>
        </header>

        {/* Content */}
        <main className="flex-1 p-6 max-w-7xl w-full">
          {page === "overview" && <OverviewDashboard />}
          {page === "battery" && <BatteryDashboard />}
          {page === "load1" && <ACMeterDashboard loadGroup="load1" label="Load Group 1" />}
          {page === "load2" && <ACMeterDashboard loadGroup="load2" label="Load Group 2" />}
          {page === "load3" && <ACMeterDashboard loadGroup="load3" label="Load Group 3" />}
          {page === "controls-load1" && <LoadControlPanel loadGroup="load1" label="Load Group 1" />}
          {page === "controls-load2" && <LoadControlPanel loadGroup="load2" label="Load Group 2" />}
          {page === "controls-load3" && <LoadControlPanel loadGroup="load3" label="Load Group 3" />}
          {page === "alerts" && (
            <AlertsFeed onUnseenChange={(n) => { if (page !== "alerts") setAlertBadge(n); }} />
          )}
        </main>

        {/* Footer */}
        <footer className="border-t border-card-border py-3 text-center text-xs text-muted">
          Smart Grid Energy Management System &middot; Live Sensor Data
        </footer>
      </div>
    </div>
  );
}

function PageTitle({ page }: { page: Page }) {
  const titles: Record<Page, { label: string; sub: string }> = {
    overview: { label: "Overview", sub: "System-wide status" },
    battery: { label: "Battery Monitor", sub: "Victron SmartShunt" },
    load1: { label: "Load Group 1", sub: "AC monitoring" },
    load2: { label: "Load Group 2", sub: "AC monitoring" },
    load3: { label: "Load Group 3", sub: "AC monitoring" },
    "controls-load1": { label: "Controls — Load Group 1", sub: "Load management" },
    "controls-load2": { label: "Controls — Load Group 2", sub: "Load management" },
    "controls-load3": { label: "Controls — Load Group 3", sub: "Load management" },
    alerts: { label: "Security Alerts", sub: "IDS engine" },
  };
  const t = titles[page];
  return (
    <div>
      <h1 className="text-sm font-semibold">{t.label}</h1>
      <p className="text-[10px] text-muted">{t.sub}</p>
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
