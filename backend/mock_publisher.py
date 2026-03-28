"""
Mock MQTT publisher — simulates ESP32 sensor data for testing.

Usage:
    pip install paho-mqtt
    python mock_publisher.py

Publishes fake battery and 3 AC load group data to the Mosquitto broker.
Run this to test the full pipeline (MQTT -> FastAPI -> WebSocket -> Dashboard)
without any ESP32 hardware.
"""

import json
import math
import random
import time

import paho.mqtt.client as mqtt

BROKER = "192.168.70.16"
PORT = 1883
INTERVAL = 0.5  # seconds between publishes

# Load group profiles — different base loads to make the data distinguishable
LOAD_PROFILES = {
    "load1": {"name": "Main Circuit",  "base_current": 10, "base_pf": 0.95},
    "load2": {"name": "HVAC System",   "base_current": 6,  "base_pf": 0.88},
    "load3": {"name": "Water Heater",  "base_current": 14, "base_pf": 0.99},
}

client = mqtt.Client()
client.connect(BROKER, PORT)
client.loop_start()

print(f"Publishing fake sensor data to {BROKER}:{PORT} every {INTERVAL}s …")
print(f"  Battery: ems/battery")
for lg in LOAD_PROFILES:
    print(f"  {LOAD_PROFILES[lg]['name']}: ems/ac/{lg}")
print("Press Ctrl+C to stop.\n")

t = 0.0
energy_acc = {lg: 0.0 for lg in LOAD_PROFILES}

try:
    while True:
        # --- Battery (simulated discharge curve) ---
        voltage = 12.8 + 0.3 * math.sin(t / 60) + random.uniform(-0.05, 0.05)
        current = -3.0 + 1.5 * math.sin(t / 30) + random.uniform(-0.2, 0.2)
        power = voltage * current
        soc = max(0, min(100, 85 + 15 * math.sin(t / 120)))
        temperature = 25 + 3 * math.sin(t / 90) + random.uniform(-0.5, 0.5)

        battery_msg = {
            "time": round(t, 1),
            "battery_voltage": round(voltage, 4),
            "battery_current": round(current, 4),
            "battery_power": round(power, 4),
            "soc": round(soc, 1),
            "consumed_ah": round(abs(current) * t / 3600, 2),
            "time_to_go": round(max(0, soc / max(0.1, abs(current))) * 0.5, 1),
            "alarm_flags": None,
            "temperature": round(temperature, 2),
        }

        client.publish("ems/battery", json.dumps(battery_msg))

        # --- 3 AC load groups (each simulates a separate PZEM-004T) ---
        now = time.localtime()
        status_parts = []

        for lg, profile in LOAD_PROFILES.items():
            # Each load has a different base current and phase offset
            phase_offset = hash(lg) % 60
            ac_voltage = 230 + 10 * math.sin(t / 45) + random.uniform(-2, 2)
            ac_current = (
                profile["base_current"]
                + (profile["base_current"] * 0.3) * math.sin((t + phase_offset) / 20)
                + random.uniform(-0.3, 0.3)
            )
            pf = profile["base_pf"] + 0.03 * math.sin(t / 40) + random.uniform(-0.01, 0.01)
            pf = min(1.0, max(0, pf))
            active_power = ac_voltage * ac_current * pf
            energy_acc[lg] += active_power * INTERVAL / 3_600_000  # kWh
            frequency = 50.0 + random.uniform(-0.05, 0.05)

            ac_msg = {
                "date": time.strftime("%Y-%m-%d", now),
                "time": time.strftime("%H:%M:%S", now),
                "ac_voltage": round(ac_voltage, 1),
                "ac_current": round(ac_current, 2),
                "active_power": round(active_power, 1),
                "active_energy": round(energy_acc[lg], 6),
                "frequency": round(frequency, 2),
                "power_factor": round(pf, 2),
            }

            client.publish(f"ems/ac/{lg}", json.dumps(ac_msg))
            status_parts.append(f"{lg}={active_power:.0f}W")

        print(f"[t={t:6.1f}] bat={voltage:.2f}V {current:+.2f}A | {' | '.join(status_parts)}")

        t += INTERVAL
        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print("\nStopped.")
    client.loop_stop()
    client.disconnect()
