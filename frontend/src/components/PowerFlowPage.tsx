"use client";

import React, { useEffect, useRef, useState } from "react";
import ReactFlow, {
  Background,
  BackgroundVariant,
  Controls,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  type NodeProps,
} from "reactflow";
import "reactflow/dist/style.css";
import { useWebSocket } from "@/hooks/useWebSocket";
import ConnectionBadge from "./ConnectionBadge";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000";

const LOAD_COLORS = {
  load1: "#3b82f6",
  load2: "#8b5cf6",
  load3: "#06b6d4",
} as const;

const SOLAR_COLOR  = "#f59e0b";
const BAT_COLOR    = "#22c55e";
const BUS_COLOR    = "#6b7280";

// ─── Sub-components ───────────────────────────────────────────────────────────

function StatRow({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <span style={{ fontSize: 10, color: "#6b7280" }}>{label}</span>
      <span style={{ fontSize: 10, color: "#e2e8f0", fontFamily: "monospace" }}>{value}</span>
    </div>
  );
}

// ─── Custom Nodes ─────────────────────────────────────────────────────────────

function SolarNode({ data }: NodeProps) {
  const { power, isCharging } = data as { power?: number; isCharging?: boolean };
  return (
    <div
      style={{
        width: 152,
        background: "#111827",
        border: `2px solid ${SOLAR_COLOR}`,
        borderRadius: 12,
        padding: 14,
        userSelect: "none",
      }}
    >
      {/* Output handle — bottom center → goes down to battery */}
      <Handle
        type="source"
        position={Position.Bottom}
        id="solar-out"
        style={{ background: SOLAR_COLOR, border: `2px solid #0b0f1a`, width: 10, height: 10 }}
      />

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 10 }}>
        <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke={SOLAR_COLOR} strokeWidth={2}>
          <circle cx="12" cy="12" r="4" />
          <path d="M12 2v2M12 20v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M2 12h2M20 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
        </svg>
        <span style={{ fontSize: 11, fontWeight: 700, color: SOLAR_COLOR, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Solar / Grid
        </span>
      </div>

      <div style={{ lineHeight: 1, marginBottom: 4 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color: SOLAR_COLOR, fontFamily: "monospace" }}>
          {power != null ? `${Number(power).toFixed(0)}` : "—"}
        </span>
        <span style={{ fontSize: 12, color: "#6b7280", marginLeft: 4 }}>W</span>
      </div>
      <p style={{ fontSize: 10, color: "#6b7280", marginBottom: 10 }}>Input Power</p>

      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.06em",
          textTransform: "uppercase",
          padding: "2px 8px",
          borderRadius: 999,
          background: isCharging ? `${SOLAR_COLOR}20` : "#1e293b",
          color:       isCharging ? SOLAR_COLOR          : "#6b7280",
        }}
      >
        {isCharging ? "Generating" : "Idle"}
      </span>
    </div>
  );
}

function BatteryNode({ data }: NodeProps) {
  const { voltage, current, power, soc, isCharging } = data as {
    voltage?: number; current?: number; power?: number;
    soc?: number | null; isCharging?: boolean;
  };

  return (
    <div
      style={{
        width: 172,
        background: "#111827",
        border: `2px solid ${BAT_COLOR}`,
        borderRadius: 12,
        padding: 16,
        userSelect: "none",
      }}
    >
      {/* Top handle — receives from solar when charging */}
      <Handle
        type="target"
        position={Position.Top}
        id="bat-top-in"
        style={{ background: BAT_COLOR, border: "2px solid #0b0f1a", width: 10, height: 10 }}
      />
      {/* Right handles — bidirectional connection to bus */}
      <Handle
        type="source"
        position={Position.Right}
        id="bat-out"
        style={{ background: BAT_COLOR, border: "2px solid #0b0f1a", width: 10, height: 10 }}
      />
      <Handle
        type="target"
        position={Position.Right}
        id="bat-in"
        style={{ background: BAT_COLOR, border: "2px solid #0b0f1a", width: 10, height: 10 }}
      />

      <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 12 }}>
        <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke={BAT_COLOR} strokeWidth={2}>
          <rect x="6" y="4" width="12" height="18" rx="2" />
          <rect x="9" y="1" width="6" height="3" rx="1" />
        </svg>
        <span style={{ fontSize: 11, fontWeight: 700, color: BAT_COLOR, letterSpacing: "0.08em", textTransform: "uppercase" }}>
          Battery
        </span>
      </div>

      <div style={{ lineHeight: 1, marginBottom: 4 }}>
        <span style={{ fontSize: 32, fontWeight: 700, color: BAT_COLOR, fontFamily: "monospace" }}>
          {soc != null ? `${Number(soc).toFixed(1)}%` : "—"}
        </span>
      </div>
      <p style={{ fontSize: 10, color: "#6b7280", textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 12 }}>
        State of Charge
      </p>

      <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 12 }}>
        <StatRow label="Voltage" value={voltage != null ? `${Number(voltage).toFixed(2)} V` : "—"} />
        <StatRow label="Current" value={current != null ? `${Number(current).toFixed(2)} A` : "—"} />
        <StatRow label="Power"   value={power   != null ? `${Number(power).toFixed(1)} W`   : "—"} />
      </div>

      <span
        style={{
          fontSize: 10,
          fontWeight: 700,
          letterSpacing: "0.08em",
          textTransform: "uppercase",
          padding: "2px 8px",
          borderRadius: 999,
          background: isCharging ? "#1d4ed820" : "#92400e20",
          color:       isCharging ? "#60a5fa"   : "#fbbf24",
        }}
      >
        {isCharging ? "Charging" : "Discharging"}
      </span>
    </div>
  );
}

function BusNode({ data }: NodeProps) {
  const { totalPower } = data as { totalPower?: number };
  return (
    <div
      style={{
        width: 110,
        background: "#111827",
        border: "1px solid #1e293b",
        borderRadius: 12,
        padding: 16,
        userSelect: "none",
      }}
    >
      {/* Left — battery connection (bidirectional) */}
      <Handle type="target" position={Position.Left} id="bus-bat-in"
        style={{ background: BUS_COLOR, border: "2px solid #0b0f1a", width: 10, height: 10 }} />
      <Handle type="source" position={Position.Left} id="bus-bat-out"
        style={{ background: BUS_COLOR, border: "2px solid #0b0f1a", width: 10, height: 10 }} />
      {/* Right — three load outputs */}
      <Handle type="source" position={Position.Right} id="right-1"
        style={{ top: "25%", background: LOAD_COLORS.load1, border: "2px solid #0b0f1a", width: 10, height: 10 }} />
      <Handle type="source" position={Position.Right} id="right-2"
        style={{ top: "50%", background: LOAD_COLORS.load2, border: "2px solid #0b0f1a", width: 10, height: 10 }} />
      <Handle type="source" position={Position.Right} id="right-3"
        style={{ top: "75%", background: LOAD_COLORS.load3, border: "2px solid #0b0f1a", width: 10, height: 10 }} />

      <p style={{ fontSize: 10, fontWeight: 600, color: BUS_COLOR, textTransform: "uppercase", letterSpacing: "0.08em", textAlign: "center", marginBottom: 8 }}>
        Bus
      </p>
      <p style={{ fontSize: 22, fontWeight: 700, color: "#e2e8f0", textAlign: "center", lineHeight: 1, fontFamily: "monospace", marginBottom: 4 }}>
        {totalPower != null ? `${Number(totalPower).toFixed(0)}` : "—"}
      </p>
      <p style={{ fontSize: 10, color: BUS_COLOR, textAlign: "center" }}>W total</p>
    </div>
  );
}

function LoadNode({ data }: NodeProps) {
  const { label, color, voltage, current, power } = data as {
    label: string; color: string;
    voltage?: number; current?: number; power?: number;
  };
  return (
    <div
      style={{
        width: 172,
        background: "#111827",
        border: "1px solid #1e293b",
        borderTop: `2px solid ${color}`,
        borderRadius: 12,
        padding: 16,
        userSelect: "none",
      }}
    >
      <Handle type="target" position={Position.Left} id="left"
        style={{ background: color, border: "2px solid #0b0f1a", width: 10, height: 10 }} />

      <p style={{ fontSize: 10, fontWeight: 700, color, textTransform: "uppercase", letterSpacing: "0.08em", marginBottom: 8 }}>
        {label}
      </p>
      <div style={{ lineHeight: 1, marginBottom: 4 }}>
        <span style={{ fontSize: 26, fontWeight: 700, color: "#e2e8f0", fontFamily: "monospace" }}>
          {power != null ? `${Number(power).toFixed(0)}` : "—"}
        </span>
        <span style={{ fontSize: 12, color: "#6b7280", marginLeft: 4 }}>W</span>
      </div>
      <p style={{ fontSize: 10, color: "#6b7280", marginBottom: 10 }}>Active Power</p>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        <StatRow label="Voltage" value={voltage != null ? `${Number(voltage).toFixed(1)} V` : "—"} />
        <StatRow label="Current" value={current != null ? `${Number(current).toFixed(2)} A` : "—"} />
      </div>
    </div>
  );
}

// ─── Node types (defined outside component to avoid re-registration) ──────────

const nodeTypes = {
  solarNode:   SolarNode,
  batteryNode: BatteryNode,
  busNode:     BusNode,
  loadNode:    LoadNode,
};

// ─── Initial positions ────────────────────────────────────────────────────────

const INITIAL_NODES = [
  { id: "solar",   type: "solarNode",   position: { x: 60,  y: -30 }, data: {} },
  { id: "battery", type: "batteryNode", position: { x: 50,  y: 195 }, data: {} },
  { id: "bus",     type: "busNode",     position: { x: 330, y: 265 }, data: {} },
  { id: "load1",   type: "loadNode",    position: { x: 560, y: 120 }, data: { label: "Load Group 1", color: LOAD_COLORS.load1 } },
  { id: "load2",   type: "loadNode",    position: { x: 560, y: 280 }, data: { label: "Load Group 2", color: LOAD_COLORS.load2 } },
  { id: "load3",   type: "loadNode",    position: { x: 560, y: 440 }, data: { label: "Load Group 3", color: LOAD_COLORS.load3 } },
];

const MAX_POWER_REF = 2000;

// ─── Interfaces ───────────────────────────────────────────────────────────────

interface BatteryPayload {
  battery_voltage: number;
  battery_current: number;
  battery_power: number;
  soc: number | null;
}

interface ACPayload {
  ac_voltage: number;
  ac_current: number;
  active_power: number;
}

// ─── SOC trend hook — determines charging state from SOC direction ────────────
// Uses a rolling window of the last N SOC readings so momentary noise doesn't
// flip the indicator. Returns true when SOC is trending upward (charging).

function useSocTrend(soc: number | null | undefined, windowSize = 8): boolean {
  const historyRef = useRef<number[]>([]);
  const [isCharging, setIsCharging] = useState(false);

  useEffect(() => {
    if (soc == null) return;
    const hist = historyRef.current;
    hist.push(soc);
    if (hist.length > windowSize) hist.shift();
    if (hist.length >= 3) {
      // Compare oldest vs newest reading in the window
      const delta = hist[hist.length - 1] - hist[0];
      if (delta > 0.02)       setIsCharging(true);
      else if (delta < -0.02) setIsCharging(false);
      // If delta is within ±0.02% keep previous state (hysteresis)
    }
  }, [soc, windowSize]);

  return isCharging;
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function PowerFlowPage() {
  const battery = useWebSocket<BatteryPayload>(`${WS_URL}/ws/battery`);
  const load1   = useWebSocket<ACPayload>(`${WS_URL}/ws/ac/load1`);
  const load2   = useWebSocket<ACPayload>(`${WS_URL}/ws/ac/load2`);
  const load3   = useWebSocket<ACPayload>(`${WS_URL}/ws/ac/load3`);

  const [nodes, setNodes, onNodesChange] = useNodesState(INITIAL_NODES);
  const [edges, setEdges, onEdgesChange] = useEdgesState([]);

  // SOC-based charging detection — reliable regardless of current sign convention
  const isCharging = useSocTrend(battery.data?.soc);

  const totalPower = (load1.data?.active_power ?? 0)
                   + (load2.data?.active_power ?? 0)
                   + (load3.data?.active_power ?? 0);

  // Inferred solar power: when charging, solar is covering load + charging battery
  const batPowerAbs = Math.abs(battery.data?.battery_power ?? 0);
  const solarPower  = isCharging ? batPowerAbs : 0;

  // Update node data on each WS tick, preserving drag positions
  useEffect(() => {
    setNodes(prev => prev.map(node => {
      switch (node.id) {
        case "solar":
          return { ...node, data: { power: solarPower, isCharging } };
        case "battery":
          return {
            ...node,
            data: {
              voltage:    battery.data?.battery_voltage,
              current:    battery.data?.battery_current,
              power:      battery.data?.battery_power,
              soc:        battery.data?.soc,
              isCharging,
            },
          };
        case "bus":
          return { ...node, data: { totalPower } };
        case "load1":
          return { ...node, data: { ...node.data, voltage: load1.data?.ac_voltage, current: load1.data?.ac_current, power: load1.data?.active_power } };
        case "load2":
          return { ...node, data: { ...node.data, voltage: load2.data?.ac_voltage, current: load2.data?.ac_current, power: load2.data?.active_power } };
        case "load3":
          return { ...node, data: { ...node.data, voltage: load3.data?.ac_voltage, current: load3.data?.ac_current, power: load3.data?.active_power } };
        default:
          return node;
      }
    }));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [battery.data, load1.data, load2.data, load3.data, isCharging]);

  // Recompute edges whenever data or charging state changes
  useEffect(() => {
    const edgeWidth = (p: number) =>
      Math.min(6, Math.max(2, 2 + (Math.abs(p) / MAX_POWER_REF) * 4));

    const l1Power = load1.data?.active_power ?? 0;
    const l2Power = load2.data?.active_power ?? 0;
    const l3Power = load3.data?.active_power ?? 0;

    // Solar → Battery: animated only when charging
    const solarEdge = {
      id: "solar-bat",
      source: "solar",   sourceHandle: "solar-out",
      target: "battery", targetHandle: "bat-top-in",
      animated: isCharging,
      style: {
        stroke: isCharging ? SOLAR_COLOR : "#1e293b",
        strokeWidth: isCharging ? edgeWidth(solarPower) : 1.5,
        opacity: isCharging ? 1 : 0.3,
      },
    };

    // Battery ↔ Bus: flip source/target to reverse dash direction
    const batBusEdge = isCharging
      ? {
          id: "bat-bus",
          source: "bus",     sourceHandle: "bus-bat-out",
          target: "battery", targetHandle: "bat-in",
          animated: true,
          style: { stroke: BAT_COLOR, strokeWidth: edgeWidth(batPowerAbs) },
        }
      : {
          id: "bat-bus",
          source: "battery", sourceHandle: "bat-out",
          target: "bus",     targetHandle: "bus-bat-in",
          animated: true,
          style: { stroke: BAT_COLOR, strokeWidth: edgeWidth(batPowerAbs) },
        };

    setEdges([
      solarEdge,
      batBusEdge,
      {
        id: "bus-l1",
        source: "bus", sourceHandle: "right-1",
        target: "load1", targetHandle: "left",
        animated: true,
        style: { stroke: LOAD_COLORS.load1, strokeWidth: edgeWidth(l1Power) },
      },
      {
        id: "bus-l2",
        source: "bus", sourceHandle: "right-2",
        target: "load2", targetHandle: "left",
        animated: true,
        style: { stroke: LOAD_COLORS.load2, strokeWidth: edgeWidth(l2Power) },
      },
      {
        id: "bus-l3",
        source: "bus", sourceHandle: "right-3",
        target: "load3", targetHandle: "left",
        animated: true,
        style: { stroke: LOAD_COLORS.load3, strokeWidth: edgeWidth(l3Power) },
      },
    ]);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [battery.data, load1.data, load2.data, load3.data, isCharging]);

  const allConnected   = battery.connected && load1.connected && load2.connected && load3.connected;
  const connectedCount = [battery, load1, load2, load3].filter(s => s.connected).length;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, height: "100%" }}>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", flexShrink: 0 }}>
        <div>
          <h1 style={{ fontSize: 20, fontWeight: 700, margin: 0 }}>Power Flow</h1>
          <p style={{ fontSize: 12, color: "#6b7280", marginTop: 2 }}>
            Live energy topology · drag nodes to rearrange
          </p>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <span style={{ fontSize: 12, color: "#6b7280" }}>{connectedCount}/4 online</span>
          <ConnectionBadge connected={allConnected} />
        </div>
      </div>

      {/* Legend */}
      <div style={{ display: "flex", gap: 20, flexShrink: 0, flexWrap: "wrap", alignItems: "center" }}>
        {[
          { label: "Solar / Grid", color: SOLAR_COLOR },
          { label: "Battery",      color: BAT_COLOR   },
          { label: "Load Group 1", color: LOAD_COLORS.load1 },
          { label: "Load Group 2", color: LOAD_COLORS.load2 },
          { label: "Load Group 3", color: LOAD_COLORS.load3 },
        ].map(({ label, color }) => (
          <div key={label} style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <div style={{ width: 24, height: 3, background: color, borderRadius: 2 }} />
            <span style={{ fontSize: 11, color: "#6b7280" }}>{label}</span>
          </div>
        ))}
        <span style={{ fontSize: 10, color: "#4b5563" }}>
          · dashes show flow direction · thicker = higher power
        </span>
      </div>

      {/* React Flow canvas */}
      <div
        style={{
          flex: 1,
          minHeight: 520,
          background: "#111827",
          border: "1px solid #1e293b",
          borderRadius: 12,
          overflow: "hidden",
        }}
      >
        <ReactFlow
          nodes={nodes}
          edges={edges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          nodeTypes={nodeTypes}
          fitView
          fitViewOptions={{ padding: 0.25 }}
          proOptions={{ hideAttribution: true }}
          minZoom={0.3}
          maxZoom={2.5}
          style={{ background: "#0b0f1a" }}
        >
          <Background variant={BackgroundVariant.Dots} gap={24} size={1.2} color="#1e293b" />
          <Controls style={{ background: "#111827", border: "1px solid #1e293b", borderRadius: 8 }} />
        </ReactFlow>
      </div>
    </div>
  );
}
