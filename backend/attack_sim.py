"""
EMS IDS Attack Simulator
========================
Demonstration script that intentionally triggers each IDS rule.
Run while mock_esp.py + backend + frontend are all live.

Usage:
    python attack_sim.py
"""

import json
import random
import sys
import time

import paho.mqtt.client as mqtt

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

BROKER = "192.168.1.130"
PORT = 1883

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_battery(**overrides) -> dict:
    payload = {
        "time":            round(time.time(), 1),
        "battery_voltage": 12.8,
        "battery_current": -3.0,
        "battery_power": -38.4,
        "soc":             85.0,
        "consumed_ah":     1.2,
        "time_to_go":      14.0,
        "alarm_flags":     None,
        "temperature":     25.0,
    }
    payload.update(overrides)
    return payload


def make_ac(**overrides) -> dict:
    payload = {
        "date":          time.strftime("%Y-%m-%d"),
        "time":          time.strftime("%H:%M:%S"),
        "ac_voltage":    230.0,
        "ac_current":    10.0,
        "active_power":  2300.0,
        "active_energy": 1.5,
        "frequency":     50.0,
        "power_factor":  0.95,
    }
    payload.update(overrides)
    return payload


def pub(client: mqtt.Client, topic: str, payload: dict | str, label: str = "") -> None:
    body = json.dumps(payload) if isinstance(payload, dict) else payload
    client.publish(topic, body)
    tag = f"  [{label}]" if label else ""
    print(f"  → {topic}{tag}  {body[:80]}{'…' if len(body) > 80 else ''}")


def banner(title: str) -> None:
    print(f"\n{'─'*55}")
    print(f"  {title}")
    print(f"{'─'*55}")


def pause(msg: str = "Press Enter to continue…") -> None:
    input(f"\n  {msg}")


# ---------------------------------------------------------------------------
# Individual attacks
# ---------------------------------------------------------------------------

def attack_flood(client: mqtt.Client) -> None:
    banner("ATTACK 1 — MQTT Flood")
    print("  Rule    : MQTTFloodRule  (limit: 60 packets / 5 s)")
    print("  Method  : Send 80 packets in ~2 seconds")
    print("  Expected: 'MQTT flood detected' warning alert\n")
    pause("Press Enter to start the flood…")

    COUNT = 80
    print(f"\n  Sending {COUNT} packets as fast as possible…")
    for i in range(COUNT):
        pub(client, "ems/battery", make_battery(), label=f"{i+1}/{COUNT}")
        time.sleep(0.025)  # ~40 pkt/s → 80 in 2 s, well over 60/5 s

    print("\n  Done. Check the Alerts page — flood warning should have fired.")


def attack_unknown_topic(client: mqtt.Client) -> None:
    banner("ATTACK 2 — Unknown Topic")
    print("  Rule    : UnknownTopicRule")
    print("  Method  : Publish on topics the backend doesn't recognise")
    print("  Expected: 'Message received on unrecognised topic' alert for each\n")
    pause("Press Enter to start…")

    fake_topics = [
        ("ems/admin/config",
         {"cmd": "set_broker", "host": "attacker.local"}),
        ("sensors/exfil",       {"battery_voltage": 12.8, "soc": 85}),
        ("home/lights/bedroom", {"state": "ON"}),
    ]

    print()
    for topic, payload in fake_topics:
        pub(client, topic, payload)
        time.sleep(0.3)

    print("\n  Done. Each unknown topic should appear as a separate alert.")


def attack_voltage_anomaly(client: mqtt.Client) -> None:
    banner("ATTACK 3 — Voltage Anomaly")
    print("  Rule    : VoltageAnomalyRule")
    print("  Method  : Publish out-of-range voltages (battery < 10 V, AC > 260 V)")
    print("  Expected: 'critical' severity voltage anomaly alerts\n")
    pause("Press Enter to start…")

    print("\n  Battery undervoltage (3.1 V)…")
    pub(client, "ems/battery", make_battery(battery_voltage=3.1))
    time.sleep(0.5)

    print("\n  Battery overvoltage (19.5 V)…")
    pub(client, "ems/battery", make_battery(battery_voltage=19.5))
    time.sleep(0.5)

    print("\n  AC overvoltage (295.0 V) on load1…")
    pub(client, "ems/ac/load1", make_ac(ac_voltage=295.0))

    print("\n  Done. Three critical alerts should appear.")


def attack_malformed(client: mqtt.Client) -> None:
    banner("ATTACK 4 — Malformed Payload")
    print("  Rule    : MalformedPayloadRule")
    print("  Method  : Send payloads with missing required fields")
    print("  Expected: 'Payload missing required fields' warning alert\n")
    pause("Press Enter to start…")

    print("\n  Completely empty battery payload…")
    pub(client, "ems/battery", {})
    time.sleep(0.5)

    print("\n  Battery payload with wrong field names…")
    pub(client, "ems/battery", {"volt": 12.8, "amp": -3.0, "watts": -38})
    time.sleep(0.5)

    print("\n  AC payload missing power and frequency…")
    pub(client, "ems/ac/load2", {"ac_voltage": 230.0, "ac_current": 10.0})

    print("\n  Done. Missing-field alerts should appear for each.")


def attack_power_spike(client: mqtt.Client) -> None:
    banner("ATTACK 5 — Power Spike")
    print("  Rule    : PowerSpikeRule  (z-score > 4.0, window: last 30 readings)")
    print("  Method  : Seed 20 normal readings (~2 300 W), then send a 12 000 W spike")
    print("  Expected: 'Power spike: X W is Y σ from recent mean' alert\n")
    pause("Press Enter to start seeding normal history…")

    SEED = 20
    print(f"\n  Publishing {SEED} normal AC readings (~2 300 W)…")
    for i in range(SEED):
        power = 2300 + (i % 5) * 10   # slight variation so stdev > 0
        pub(client, "ems/ac/load3",
            make_ac(active_power=float(power)), label=f"{i+1}/{SEED}")
        time.sleep(0.1)

    print("\n  Seeding complete. Sending spike (12 000 W)…")
    time.sleep(0.3)
    pub(client, "ems/ac/load3", make_ac(active_power=12000.0), label="SPIKE")

    print("\n  Done. A power spike alert with a high z-score should appear.")


def attack_voltage_trend(client: mqtt.Client) -> None:
    banner("ATTACK 6 — Voltage Trend (Sustained Decline)")
    print("  Rule    : VoltageTrendRule  (20 consecutive decreasing readings)")
    print("  Method  : Publish 22 battery messages with strictly falling voltage")
    print("  Expected: 'Battery voltage declining for 20 consecutive readings' alert\n")
    pause("Press Enter to start the decline…")

    START_V = 13.5
    STEPS = 22
    print(
        f"\n  Sending {STEPS} readings: {START_V:.2f} V → {START_V - STEPS*0.1:.2f} V\n")

    for i in range(STEPS):
        v = round(START_V - i * 0.1, 3)
        pub(client, "ems/battery",
            make_battery(battery_voltage=v), label=f"step {i+1}")
        time.sleep(0.15)

    print("\n  Done. Voltage trend alert should appear after reading 20.")


# ---------------------------------------------------------------------------
# Anomaly-monitor attacks (trigger statistical / ML detection, not just IDS rules)
# ---------------------------------------------------------------------------

def attack_anomaly_power_surge(client: mqtt.Client) -> None:
    banner("ATTACK 7 — Power Surge (Anomaly Monitor)")
    print("  Target  : load1_active_power, load2_active_power, load3_active_power")
    print("  Method  : Seed 20 normal readings, then inject sustained 8 000 W surge")
    print("  Expected: critical anomalies on Anomaly Monitor within ~10 s\n")
    print("  NOTE    : The anomaly engine runs every 5 s and reads from the CSV log.")
    print("            Anomalies appear on the Anomaly Monitor page, not Alerts.\n")
    pause("Press Enter to begin seeding normal history…")

    SEED = 20
    print(f"\n  Publishing {SEED} normal AC readings (~2 300 W) on all three load groups…")
    for i in range(SEED):
        power = 2300.0 + (i % 5) * 8
        for lg in ["load1", "load2", "load3"]:
            pub(client, f"ems/ac/{lg}", make_ac(active_power=power), label=f"{lg} {i+1}/{SEED}")
        time.sleep(0.25)

    print("\n  Seeding complete. Injecting 8 000 W surge on all load groups…")
    SURGE = 15
    for i in range(SURGE):
        surge_power = 8000.0 + (i % 3) * 200
        for lg in ["load1", "load2", "load3"]:
            pub(client, f"ems/ac/{lg}", make_ac(active_power=surge_power), label=f"SURGE {i+1}/{SURGE}")
        time.sleep(0.3)

    print("\n  Surge complete. Wait ~10 s for the anomaly engine to process.")
    print("  Check the Anomaly Monitor page for critical anomalies on active_power signals.")


def attack_anomaly_frequency_deviation(client: mqtt.Client) -> None:
    banner("ATTACK 8 — Frequency Deviation (Anomaly Monitor)")
    print("  Target  : load1_frequency, load2_frequency, load3_frequency")
    print("  Method  : Seed normal 50 Hz history, then sustain 44 Hz (grid instability)")
    print("  Expected: high/critical anomalies on frequency signals\n")
    pause("Press Enter to begin seeding normal history…")

    SEED = 20
    print(f"\n  Publishing {SEED} normal readings at 50.0 Hz…")
    for i in range(SEED):
        freq = 50.0 + random.uniform(-0.05, 0.05)
        for lg in ["load1", "load2", "load3"]:
            pub(client, f"ems/ac/{lg}", make_ac(frequency=round(freq, 3)), label=f"{lg} {i+1}/{SEED}")
        time.sleep(0.25)

    print("\n  Injecting sustained 44 Hz frequency deviation…")
    DEVIATE = 15
    for i in range(DEVIATE):
        bad_freq = 44.0 + random.uniform(-0.2, 0.2)
        for lg in ["load1", "load2", "load3"]:
            pub(client, f"ems/ac/{lg}", make_ac(frequency=round(bad_freq, 3)), label=f"44Hz {i+1}/{DEVIATE}")
        time.sleep(0.3)

    print("\n  Done. Check the Anomaly Monitor for frequency signal anomalies.")


def attack_anomaly_battery_soc(client: mqtt.Client) -> None:
    banner("ATTACK 9 — Battery SOC Crash (Anomaly Monitor)")
    print("  Target  : battery_soc, battery_voltage, battery_current")
    print("  Method  : Seed normal ~85 % SOC readings, then simulate rapid drain to 4 %")
    print("  Expected: critical anomalies on battery_soc and battery_voltage signals\n")
    pause("Press Enter to begin seeding normal battery history…")

    SEED = 20
    print(f"\n  Publishing {SEED} normal battery readings (SOC ~85 %, voltage ~12.8 V)…")
    for i in range(SEED):
        soc = 85.0 + random.uniform(-0.5, 0.5)
        pub(client, "ems/battery",
            make_battery(soc=round(soc, 2), battery_voltage=12.8, battery_current=-2.8),
            label=f"{i+1}/{SEED}")
        time.sleep(0.25)

    print("\n  Simulating catastrophic SOC crash (4 %) and undervoltage (9.8 V)…")
    CRASH = 15
    for i in range(CRASH):
        soc = 4.0 + random.uniform(0, 1.5)
        voltage = 9.8 + random.uniform(-0.1, 0.1)
        current = -0.3 + random.uniform(-0.05, 0.05)
        power = voltage * current
        pub(client, "ems/battery",
            make_battery(soc=round(soc, 2), battery_voltage=round(voltage, 3),
                         battery_current=round(current, 3), battery_power=round(power, 3)),
            label=f"CRASH {i+1}/{CRASH}")
        time.sleep(0.3)

    print("\n  Done. Check the Anomaly Monitor for battery signal anomalies.")
    print("  (The IDS voltage rule may also fire a separate critical alert.)")


# ---------------------------------------------------------------------------
# Menu
# ---------------------------------------------------------------------------

ATTACKS = [
    # ── IDS / Alert rules ──────────────────────────────────────────────────
    ("MQTT Flood",                  "Flood broker with 80 packets in 2 seconds",
     attack_flood),
    ("Unknown Topic",               "Publish on unrecognised MQTT topics",
     attack_unknown_topic),
    ("Voltage Anomaly",             "Send out-of-range battery and AC voltages",
     attack_voltage_anomaly),
    ("Malformed Payload",           "Send payloads with missing required fields",
     attack_malformed),
    ("Power Spike",                 "Seed normal history then inject a 12 000 W spike",
     attack_power_spike),
    ("Voltage Trend",               "22 strictly decreasing battery voltage readings",
     attack_voltage_trend),
    # ── Anomaly Monitor (statistical / ML detection) ───────────────────────
    ("Power Surge  [ANOMALY]",      "Seed 2 300 W baseline, surge to 8 000 W on all loads",
     attack_anomaly_power_surge),
    ("Frequency Deviation [ANOMALY]", "Seed 50 Hz baseline, sustain 44 Hz on all loads",
     attack_anomaly_frequency_deviation),
    ("Battery SOC Crash  [ANOMALY]","Seed 85 % SOC baseline, crash to 4 % / 9.8 V",
     attack_anomaly_battery_soc),
]


def menu() -> None:
    print("\n" + "="*60)
    print("  EMS Attack Simulator")
    print("  Make sure mock_esp + backend + frontend are running.")
    print("="*60)
    print("\n  ── IDS Alerts (trigger immediately) ──")
    for i, (name, desc, _) in enumerate(ATTACKS[:6], 1):
        print(f"  [{i}] {name}")
        print(f"       {desc}")
    print("\n  ── Anomaly Monitor (statistical, ~10 s lag) ──")
    for i, (name, desc, _) in enumerate(ATTACKS[6:], 7):
        print(f"  [{i}] {name}")
        print(f"       {desc}")
    print()
    print("  [A] Run ALL attacks in sequence")
    print("  [Q] Quit")


def main() -> None:
    print("\n  Connecting to MQTT broker…")
    client = mqtt.Client()
    try:
        client.connect(BROKER, PORT)
        client.loop_start()
        print(f"  Connected to {BROKER}:{PORT}\n")
    except Exception as e:
        print(f"\n  ERROR: Could not connect to broker — {e}")
        sys.exit(1)

    try:
        while True:
            menu()
            choice = input("\n  Your choice: ").strip().upper()

            if choice == "Q":
                break
            elif choice == "A":
                for _, _, fn in ATTACKS:
                    fn(client)
                    pause("Attack done. Press Enter for the next one…")
                print("\n  All attacks complete.")
            elif choice.isdigit() and 1 <= int(choice) <= len(ATTACKS):
                _, _, fn = ATTACKS[int(choice) - 1]
                fn(client)
            else:
                print("  Invalid choice, try again.")

    except KeyboardInterrupt:
        pass
    finally:
        client.loop_stop()
        client.disconnect()
        print("\n  Disconnected. Goodbye.\n")


if __name__ == "__main__":
    main()
