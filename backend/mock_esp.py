"""
Mock ESP32 — simulates a real ESP32 sensor node for pipeline testing.

Behaves like the real ESP32 would:
  - Publishes battery (ems/battery) and AC load data (ems/ac/load1/2/3) every 0.5s
  - Subscribes to ems/control/# and reacts to control commands:
      relay: "ON" / "OFF"   → enables / disables AC output for that load group
      threshold: <watts>     → auto-trips relay if power exceeds the limit
      priority: <level>      → stored and displayed, no effect on mock data
      on_time / off_time     → stored and displayed

Usage:
    pip install paho-mqtt
    python mock_esp.py
"""

import json
import math
import random
import time

import paho.mqtt.client as mqtt

BROKER = "192.168.1.130"
PORT = 1883
INTERVAL = 0.5  # seconds between publishes

LOAD_PROFILES = {
    "load1": {"name": "Main Circuit",  "base_current": 10, "base_pf": 0.95},
    "load2": {"name": "HVAC System",   "base_current": 6,  "base_pf": 0.88},
    "load3": {"name": "Water Heater",  "base_current": 14, "base_pf": 0.99},
}

# Per-load-group state (mutated by on_message from the MQTT subscriber thread)
relay_state:    dict[str, str] = {lg: "ON" for lg in LOAD_PROFILES}
power_threshold: dict[str, float | None] = {lg: None for lg in LOAD_PROFILES}
schedule:       dict[str, dict] = {
    lg: {"on_time": None, "off_time": None} for lg in LOAD_PROFILES}
priority:       dict[str, str] = {lg: "Normal" for lg in LOAD_PROFILES}


def publish_status(mqtt_client, load_group: str) -> None:
    """Publish the current state for a load group to ems/status/{load_group}."""
    state = {
        "relay":     relay_state[load_group],
        "threshold": power_threshold[load_group],
        "on_time":   schedule[load_group]["on_time"],
        "off_time":  schedule[load_group]["off_time"],
        "priority":  priority[load_group],
    }
    mqtt_client.publish(
        f"ems/status/{load_group}", json.dumps(state), retain=True)


def on_message(mqtt_client, userdata, msg):
    topic = msg.topic          # e.g. "ems/control/load1"
    load_group = topic.split("/")[-1]
    ts = time.strftime("%H:%M:%S")

    if load_group not in LOAD_PROFILES:
        return

    try:
        payload = json.loads(msg.payload.decode())
    except (json.JSONDecodeError, UnicodeDecodeError):
        raw = msg.payload.decode(errors="replace")
        print(
            f"\n[CONTROL] {ts} → {load_group.upper()} | BAD PAYLOAD: {raw}\n")
        return

    # --- Apply state changes ---
    if "relay" in payload:
        relay_state[load_group] = str(payload["relay"]).upper()

    if "threshold" in payload:
        val = payload["threshold"]
        power_threshold[load_group] = float(
            val) if val not in (None, "", 0, "0") else None

    if "on_time" in payload:
        schedule[load_group]["on_time"] = payload["on_time"] or None

    if "off_time" in payload:
        schedule[load_group]["off_time"] = payload["off_time"] or None

    if "priority" in payload:
        priority[load_group] = str(payload["priority"])

    # --- Report new state back so backend stays in sync ---
    publish_status(mqtt_client, load_group)

    # --- Pretty-print ---
    fields = " | ".join(f"{k}: {v}" for k, v in payload.items())
    relay_icon = "🟢" if relay_state[load_group] == "ON" else "🔴"
    thr = f"{power_threshold[load_group]:.0f}W" if power_threshold[load_group] else "none"

    print(f"\n{'='*55}")
    print(f"  [CONTROL] {ts}  →  {load_group.upper()}")
    print(f"  command : {fields}")
    print(
        f"  state   : relay={relay_icon}{relay_state[load_group]}  threshold={thr}  priority={priority[load_group]}")
    print(f"{'='*55}\n")


# --------------------------------------------------------------------------
# MQTT client
# --------------------------------------------------------------------------

client = mqtt.Client()
client.on_message = on_message
client.connect(BROKER, PORT)
client.subscribe("ems/control/#")
client.loop_start()

# Announce initial state so backend control_state is populated immediately
for lg in LOAD_PROFILES:
    publish_status(client, lg)

print(f"[mock-esp] Connected to {BROKER}:{PORT}")
print(f"  Publishing  → ems/battery, ems/ac/load1, ems/ac/load2, ems/ac/load3")
print(f"  Status      → ems/status/load1, ems/status/load2, ems/status/load3")
print(f"  Listening   ← ems/control/#")
print("Press Ctrl+C to stop.\n")

# --------------------------------------------------------------------------
# Publish loop
# --------------------------------------------------------------------------

t = 0.0
energy_acc = {lg: 0.0 for lg in LOAD_PROFILES}

try:
    while True:
        # --- Battery ---
        voltage = 12.8 + 0.3 * math.sin(t / 60) + random.uniform(-0.05, 0.05)
        current = -3.0 + 1.5 * math.sin(t / 30) + random.uniform(-0.2,  0.2)
        power = voltage * current
        soc = max(0, min(100, 85 + 15 * math.sin(t / 120)))
        temperature = 25 + 3 * math.sin(t / 90) + random.uniform(-0.5,  0.5)

        battery_msg = {
            "time":            round(t, 1),
            "battery_voltage": round(voltage, 4),
            "battery_current": round(current, 4),
            "battery_power":   round(power,   4),
            "soc":             round(soc,      1),
            "consumed_ah":     round(abs(current) * t / 3600, 2),
            "time_to_go":      round(max(0, soc / max(0.1, abs(current))) * 0.5, 1),
            "alarm_flags":     None,
            "temperature":     round(temperature, 2),
        }
        client.publish("ems/battery", json.dumps(battery_msg))

        # --- AC load groups ---
        now = time.localtime()
        status_parts = []

        for lg, profile in LOAD_PROFILES.items():
            if relay_state[lg] == "OFF":
                # Relay open → publish zeros (circuit is off)
                ac_msg = {
                    "date":         time.strftime("%Y-%m-%d", now),
                    "time":         time.strftime("%H:%M:%S", now),
                    "ac_voltage":   0.0,
                    "ac_current":   0.0,
                    "active_power": 0.0,
                    "active_energy": round(energy_acc[lg], 6),
                    "frequency":    0.0,
                    "power_factor": 0.0,
                }
                client.publish(f"ems/ac/{lg}", json.dumps(ac_msg))
                status_parts.append(f"{lg}=OFF")
                continue

            phase_offset = hash(lg) % 60
            ac_voltage = 230 + 10 * math.sin(t / 45) + random.uniform(-2, 2)
            ac_current = (
                profile["base_current"]
                + (profile["base_current"] * 0.3) *
                math.sin((t + phase_offset) / 20)
                + random.uniform(-0.3, 0.3)
            )
            pf = profile["base_pf"] + 0.03 * \
                math.sin(t / 40) + random.uniform(-0.01, 0.01)
            pf = min(1.0, max(0.0, pf))
            active_power = ac_voltage * ac_current * pf
            energy_acc[lg] += active_power * INTERVAL / 3_600_000  # kWh
            frequency = 50.0 + random.uniform(-0.05, 0.05)

            # Auto-trip if threshold exceeded
            thr = power_threshold[lg]
            if thr is not None and active_power > thr:
                relay_state[lg] = "OFF"
                publish_status(client, lg)
                print(
                    f"\n[TRIP] {lg} tripped! {active_power:.0f}W > threshold {thr:.0f}W → relay OFF\n")

            ac_msg = {
                "date":          time.strftime("%Y-%m-%d", now),
                "time":          time.strftime("%H:%M:%S", now),
                "ac_voltage":    round(ac_voltage,   1),
                "ac_current":    round(ac_current,   2),
                "active_power":  round(active_power, 1),
                "active_energy": round(energy_acc[lg], 6),
                "frequency":     round(frequency,    2),
                "power_factor":  round(pf,            2),
            }
            client.publish(f"ems/ac/{lg}", json.dumps(ac_msg))
            status_parts.append(f"{lg}={active_power:.0f}W")

        relay_icons = "".join(
            ("🟢" if relay_state[lg] == "ON" else "🔴") for lg in LOAD_PROFILES
        )
        print(
            f"[t={t:6.1f}] bat={voltage:.2f}V {current:+.2f}A  {relay_icons}  {' | '.join(status_parts)}")

        t += INTERVAL
        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print("\n[mock-esp] Stopped.")
    client.loop_stop()
    client.disconnect()
