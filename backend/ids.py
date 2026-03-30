"""
Signature-based IDS for the EMS backend.

Each Rule receives (topic, payload, history) and returns an Alert or None.
Add new rules by:
  1. Subclassing Rule and implementing evaluate()
  2. Appending an instance to RULES at the bottom of this file
"""

from __future__ import annotations

import math
import statistics
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# Alert
# ---------------------------------------------------------------------------

@dataclass
class Alert:
    id: str
    timestamp: str          # ISO 8601 UTC
    rule: str               # rule name key
    severity: str           # "info" | "warning" | "critical"
    topic: str              # MQTT topic that triggered it
    message: str            # human-readable description
    data: dict[str, Any] = field(default_factory=dict)


# Global alert store — last 200 alerts, newest at the right
alerts: deque[Alert] = deque(maxlen=200)

# ---------------------------------------------------------------------------
# Rule base class
# ---------------------------------------------------------------------------

class Rule:
    name: str = "base"
    severity: str = "info"

    def evaluate(
        self,
        topic: str,
        payload: dict[str, Any],
        history: list[dict[str, Any]],
    ) -> Alert | None:
        return None

    def _alert(self, topic: str, message: str, data: dict | None = None) -> Alert:
        return Alert(
            id=str(uuid.uuid4()),
            timestamp=datetime.now(timezone.utc).isoformat(),
            rule=self.name,
            severity=self.severity,
            topic=topic,
            message=message,
            data=data or {},
        )

# ---------------------------------------------------------------------------
# Rule: MQTT Flood
# Fires when too many packets arrive in a short sliding window.
# Counts ALL topics together, not per-topic.
# ---------------------------------------------------------------------------

class MQTTFloodRule(Rule):
    """Alert if more than `limit` MQTT messages arrive within `window` seconds."""

    name = "mqtt_flood"
    severity = "warning"

    def __init__(self, limit: int = 60, window: float = 5.0):
        self.limit = limit
        self.window = window
        self._timestamps: deque[float] = deque()
        self._alerted = False  # suppress repeated alerts for the same burst

    def evaluate(self, topic, payload, history):
        now = time.monotonic()
        self._timestamps.append(now)
        # Evict timestamps outside the window
        while self._timestamps and self._timestamps[0] < now - self.window:
            self._timestamps.popleft()

        count = len(self._timestamps)
        if count > self.limit:
            if not self._alerted:
                self._alerted = True
                return self._alert(
                    topic,
                    f"MQTT flood detected: {count} packets in {self.window}s "
                    f"(limit {self.limit})",
                    {"packet_count": count, "window_seconds": self.window},
                )
        else:
            self._alerted = False  # reset so next burst fires again
        return None


# ---------------------------------------------------------------------------
# Rule: Unknown Topic
# Fires when a message arrives on a topic we don't recognise.
# ---------------------------------------------------------------------------

KNOWN_PREFIXES = (
    "ems/battery",
    "ems/ac/",
    "ems/status/",
    "ems/control/",
)

class UnknownTopicRule(Rule):
    """Alert on messages from unexpected MQTT topics."""

    name = "unknown_topic"
    severity = "warning"

    def evaluate(self, topic, payload, history):
        if not any(topic.startswith(p) for p in KNOWN_PREFIXES):
            return self._alert(
                topic,
                f"Message received on unrecognised topic: {topic}",
                {"topic": topic},
            )
        return None


# ---------------------------------------------------------------------------
# Rule: Voltage Anomaly
# Fires when battery or AC voltage is outside safe operating range.
# ---------------------------------------------------------------------------

class VoltageAnomalyRule(Rule):
    """Alert when voltage goes outside expected bounds."""

    name = "voltage_anomaly"
    severity = "critical"

    BATTERY_MIN = 10.0
    BATTERY_MAX = 16.0
    AC_MIN = 200.0
    AC_MAX = 260.0

    def evaluate(self, topic, payload, history):
        if topic == "ems/battery":
            v = payload.get("battery_voltage")
            if v is not None and not math.isnan(float(v)):
                v = float(v)
                if not (self.BATTERY_MIN <= v <= self.BATTERY_MAX):
                    return self._alert(
                        topic,
                        f"Battery voltage {v:.2f} V outside safe range "
                        f"[{self.BATTERY_MIN}, {self.BATTERY_MAX}] V",
                        {"voltage": v},
                    )

        elif topic.startswith("ems/ac/"):
            v = payload.get("ac_voltage")
            if v is not None and not math.isnan(float(v)):
                v = float(v)
                if not (self.AC_MIN <= v <= self.AC_MAX):
                    return self._alert(
                        topic,
                        f"AC voltage {v:.1f} V outside safe range "
                        f"[{self.AC_MIN}, {self.AC_MAX}] V",
                        {"voltage": v},
                    )
        return None


# ---------------------------------------------------------------------------
# Rule: Malformed Payload
# Fires when a known topic is missing required fields.
# ---------------------------------------------------------------------------

REQUIRED_FIELDS: dict[str, set[str]] = {
    "ems/battery": {"battery_voltage", "battery_current", "battery_power"},
}
AC_REQUIRED = {"ac_voltage", "ac_current", "active_power", "frequency"}

class MalformedPayloadRule(Rule):
    """Alert when a known payload is missing required fields."""

    name = "malformed_payload"
    severity = "warning"

    def evaluate(self, topic, payload, history):
        required: set[str] | None = None

        if topic in REQUIRED_FIELDS:
            required = REQUIRED_FIELDS[topic]
        elif topic.startswith("ems/ac/"):
            required = AC_REQUIRED

        if required:
            missing = required - set(payload.keys())
            if missing:
                return self._alert(
                    topic,
                    f"Payload missing required fields: {sorted(missing)}",
                    {"missing_fields": sorted(missing)},
                )
        return None


# ---------------------------------------------------------------------------
# Rule: Power Spike (historical)
# Fires when active_power deviates more than N standard deviations from
# the recent mean across the last `window` readings.
# Requires at least `min_samples` history entries before activating.
# ---------------------------------------------------------------------------

class PowerSpikeRule(Rule):
    """Alert when active_power is a statistical outlier vs recent history."""

    name = "power_spike"
    severity = "warning"

    def __init__(self, z_threshold: float = 4.0, window: int = 30, min_samples: int = 10):
        self.z_threshold = z_threshold
        self.window = window
        self.min_samples = min_samples

    def evaluate(self, topic, payload, history):
        if not topic.startswith("ems/ac/"):
            return None

        power = payload.get("active_power")
        if power is None:
            return None

        recent = [
            r["active_power"]
            for r in history[-self.window :]
            if r.get("active_power") is not None
        ]

        if len(recent) < self.min_samples:
            return None

        mean = statistics.mean(recent)
        stdev = statistics.stdev(recent)

        if stdev < 1.0:  # avoid division by near-zero
            return None

        z = abs(float(power) - mean) / stdev
        if z > self.z_threshold:
            return self._alert(
                topic,
                f"Power spike: {power:.0f} W is {z:.1f}σ from recent mean "
                f"({mean:.0f} W ± {stdev:.0f} W)",
                {"power": power, "mean": round(mean, 1), "stdev": round(stdev, 1), "z_score": round(z, 2)},
            )
        return None


# ---------------------------------------------------------------------------
# Rule: Voltage Trend (historical)
# Fires when battery voltage has been monotonically declining for the last
# `window` consecutive readings — indicating a sustained discharge or fault.
# ---------------------------------------------------------------------------

class VoltageTrendRule(Rule):
    """Alert when battery voltage has been declining for N consecutive readings."""

    name = "voltage_trend"
    severity = "warning"

    def __init__(self, window: int = 20):
        self.window = window

    def evaluate(self, topic, payload, history):
        if topic != "ems/battery":
            return None

        voltages = [
            r["battery_voltage"]
            for r in history[-(self.window + 1) :]
            if r.get("battery_voltage") is not None
        ]

        if len(voltages) < self.window:
            return None

        # Check strict monotonic decline
        if all(voltages[i] > voltages[i + 1] for i in range(len(voltages) - 1)):
            drop = voltages[0] - voltages[-1]
            return self._alert(
                topic,
                f"Battery voltage declining for {self.window} consecutive readings "
                f"({voltages[0]:.2f} V → {voltages[-1]:.2f} V, −{drop:.2f} V)",
                {"start_v": round(voltages[0], 3), "end_v": round(voltages[-1], 3), "drop": round(drop, 3)},
            )
        return None


# ---------------------------------------------------------------------------
# Rule registry — edit this list to add/remove rules
# ---------------------------------------------------------------------------

RULES: list[Rule] = [
    MQTTFloodRule(limit=60, window=5.0),
    UnknownTopicRule(),
    VoltageAnomalyRule(),
    MalformedPayloadRule(),
    PowerSpikeRule(z_threshold=4.0, window=30, min_samples=10),
    VoltageTrendRule(window=20),
]

# ---------------------------------------------------------------------------
# Evaluation entry point — called by main.py for every MQTT message
# ---------------------------------------------------------------------------

def evaluate_all(
    topic: str,
    payload: dict[str, Any],
    history: list[dict[str, Any]],
) -> list[Alert]:
    """Run all rules. Append triggered alerts to the global store and return them."""
    triggered: list[Alert] = []
    for rule in RULES:
        try:
            alert = rule.evaluate(topic, payload, history)
            if alert:
                alerts.append(alert)
                triggered.append(alert)
        except Exception:
            # A buggy rule must never crash the backend
            pass
    return triggered
