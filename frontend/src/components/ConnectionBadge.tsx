"use client";

import React from "react";

export default function ConnectionBadge({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-2 text-xs font-medium">
      <span
        className={`w-2 h-2 rounded-full ${connected ? "bg-accent-green status-blink" : "bg-accent-red"}`}
      />
      <span className={connected ? "text-accent-green" : "text-accent-red"}>
        {connected ? "LIVE" : "DISCONNECTED"}
      </span>
    </div>
  );
}
