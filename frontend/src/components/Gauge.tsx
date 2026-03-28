"use client";

import React from "react";

interface GaugeProps {
  label: string;
  value: number | null;
  min: number;
  max: number;
  unit: string;
  color: string;
  decimals?: number;
}

export default function Gauge({ label, value, min, max, unit, color, decimals = 2 }: GaugeProps) {
  const pct = value !== null ? Math.min(Math.max((value - min) / (max - min), 0), 1) : 0;
  const angle = -135 + pct * 270; // sweep from -135° to +135°

  const r = 48;
  const cx = 72;
  const cy = 62;

  const startAngle = -135;
  const endAngle = 135;
  const totalSweep = endAngle - startAngle;

  const toRad = (deg: number) => (deg * Math.PI) / 180;

  const arcPath = (from: number, to: number) => {
    const x1 = cx + r * Math.cos(toRad(from));
    const y1 = cy + r * Math.sin(toRad(from));
    const x2 = cx + r * Math.cos(toRad(to));
    const y2 = cy + r * Math.sin(toRad(to));
    const sweep = to - from;
    const large = sweep > 180 ? 1 : 0;
    return `M ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2}`;
  };

  const bgPath = arcPath(startAngle, endAngle);
  const valuePath = pct > 0.005 ? arcPath(startAngle, startAngle + pct * totalSweep) : "";

  const needleX = cx + (r - 10) * Math.cos(toRad(angle));
  const needleY = cy + (r - 10) * Math.sin(toRad(angle));

  return (
    <div className="flex flex-col items-center rounded-xl border border-card-border bg-card p-4 min-w-[170px]">
      <svg viewBox="0 0 144 110" className="w-36 h-28" overflow="visible">
        {/* Background track */}
        <path d={bgPath} fill="none" stroke="#1e293b" strokeWidth="10" strokeLinecap="round" />
        {/* Value arc */}
        {valuePath && (
          <path
            d={valuePath}
            fill="none"
            stroke={color}
            strokeWidth="10"
            strokeLinecap="round"
            style={{ filter: `drop-shadow(0 0 6px ${color})` }}
          />
        )}
        {/* Needle */}
        <line
          x1={cx}
          y1={cy}
          x2={needleX}
          y2={needleY}
          stroke="#e2e8f0"
          strokeWidth="2"
          strokeLinecap="round"
        />
        <circle cx={cx} cy={cy} r="3" fill="#e2e8f0" />
        {/* Value text */}
        <text x={cx} y={cy + 22} textAnchor="middle" fill={color} fontSize="14" fontWeight="bold" fontFamily="monospace">
          {value !== null ? value.toFixed(decimals) : "—"}
        </text>
        <text x={cx} y={cy + 33} textAnchor="middle" fill="#64748b" fontSize="8" fontFamily="sans-serif">
          {unit}
        </text>
      </svg>
      <span className="text-xs text-muted mt-1 font-medium tracking-wide uppercase">{label}</span>
    </div>
  );
}
