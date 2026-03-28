"""
Mock MQTT publisher — simulates ESP32 sensor data for testing.

Usage:
    pip install paho-mqtt
    python mock_publisher.py

Publishes fake battery and AC data to the Mosquitto broker on localhost:1883.
Run this to test the full pipeline (MQTT → FastAPI → WebSocket → Dashboard)
without any ESP32 hardware.
"""

import json
import math
import random
import time

import paho.mqtt.client as mqtt

BROKER = "localhost"
PORT = 1883
INTERVAL = 0.5  # seconds between publishes

client = mqtt.Client()
client.connect(BROKER, PORT)
client.loop_start()

print(f"Publishing fake sensor data to {BROKER}:{PORT} every {INTERVAL}s …")
print("Press Ctrl+C to stop.\n")

t = 0.0
energy_acc = 0.0

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

        # --- AC meter (simulated household load) ---
        ac_voltage = 230 + 10 * math.sin(t / 45) + random.uniform(-2, 2)
        ac_current = 8 + 4 * math.sin(t / 20) + random.uniform(-0.5, 0.5)
        active_power = ac_voltage * ac_current * 0.95
        energy_acc += active_power * INTERVAL / 3_600_000  # kWh
        frequency = 50.0 + random.uniform(-0.05, 0.05)
        pf = 0.92 + 0.06 * math.sin(t / 40) + random.uniform(-0.01, 0.01)

        now = time.localtime()
        ac_msg = {
            "date": time.strftime("%Y-%m-%d", now),
            "time": time.strftime("%H:%M:%S", now),
            "ac_voltage": round(ac_voltage, 1),
            "ac_current": round(ac_current, 2),
            "active_power": round(active_power, 1),
            "active_energy": round(energy_acc, 6),
            "frequency": round(frequency, 2),
            "power_factor": round(min(1.0, max(0, pf)), 2),
        }

        client.publish("ems/ac", json.dumps(ac_msg))

        print(f"[t={t:6.1f}] battery={voltage:.2f}V {current:+.2f}A | ac={ac_voltage:.0f}V {active_power:.0f}W")

        t += INTERVAL
        time.sleep(INTERVAL)

except KeyboardInterrupt:
    print("\nStopped.")
    client.loop_stop()
    client.disconnect()
