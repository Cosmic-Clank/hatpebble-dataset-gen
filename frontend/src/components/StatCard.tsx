"use client";

import React from "react";

interface StatCardProps {
  label: string;
  value: string | number | null;
  unit: string;
  color: string;
}

export default function StatCard({ label, value, unit, color }: StatCardProps) {
  return (
    <div className="rounded-xl border border-card-border bg-card p-4 flex flex-col gap-1 min-w-[140px]">
      <span className="text-xs text-muted uppercase tracking-wide font-medium">{label}</span>
      <div className="flex items-baseline gap-1">
        <span className="text-2xl font-bold font-mono" style={{ color }}>
          {value ?? "—"}
        </span>
        <span className="text-xs text-muted">{unit}</span>
      </div>
    </div>
  );
}
