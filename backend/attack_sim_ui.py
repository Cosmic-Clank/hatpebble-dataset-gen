"""
EMS Attack Simulator — Web UI
Standalone — runs on port 7000 (default), separate from the main backend.
Usage:
    python attack_sim_ui.py
    python attack_sim_ui.py --broker 192.168.1.130 --mqtt-port 1883 --ui-port 7000
Then open http://localhost:7000 in your browser.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import time
import threading
from collections import deque
from datetime import datetime
from typing import Any

import paho.mqtt.client as mqtt
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

log = logging.getLogger("attack_sim_ui")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
_client: mqtt.Client | None = None
_broker_host = "192.168.1.130"
_broker_port = 1883
_connected = False
_log_queue: deque[dict] = deque(maxlen=500)
_running_attack: str | None = None

# ---------------------------------------------------------------------------
# Log helper
# ---------------------------------------------------------------------------
def _log(msg: str, level: str = "info", topic: str = "", payload: str = "") -> None:
    entry = {
        "ts": datetime.now().strftime("%H:%M:%S.%f")[:-3],
        "level": level,
        "msg": msg,
        "topic": topic,
        "payload": payload[:100] + ("…" if len(payload) > 100 else ""),
    }
    _log_queue.append(entry)
    getattr(log, level, log.info)(msg)

# ---------------------------------------------------------------------------
# MQTT helpers
# ---------------------------------------------------------------------------
def make_battery(**kw) -> dict:
    d = {
        "time": round(time.time(), 1),
        "battery_voltage": 12.8, "battery_current": -3.0, "battery_power": -38.4,
        "soc": 85.0, "consumed_ah": 1.2, "time_to_go": 14.0,
        "alarm_flags": None, "temperature": 25.0,
    }
    d.update(kw)
    return d

def make_ac(**kw) -> dict:
    d = {
        "date": time.strftime("%Y-%m-%d"), "time": time.strftime("%H:%M:%S"),
        "ac_voltage": 230.0, "ac_current": 10.0, "active_power": 2300.0,
        "active_energy": 1.5, "frequency": 50.0, "power_factor": 0.95,
    }
    d.update(kw)
    return d

def pub(topic: str, payload: dict | str, label: str = "") -> None:
    global _client
    if not _client or not _connected:
        _log("Not connected — packet dropped", "warning")
        return
    body = json.dumps(payload) if isinstance(payload, dict) else payload
    _client.publish(topic, body)
    tag = f" [{label}]" if label else ""
    _log(f"→ {topic}{tag}", "info", topic=topic, payload=body)

def _ms(interval_ms: int) -> None:
    time.sleep(max(interval_ms, 10) / 1000.0)

# ---------------------------------------------------------------------------
# Custom attack implementations
# ---------------------------------------------------------------------------
def _run_power_surge(p: dict) -> None:
    targets = p.get("targets") or ["load1", "load2", "load3"]
    baseline = float(p.get("baseline_w", 2300))
    surge = float(p.get("surge_w", 8000))
    seed_n = int(p.get("seed_count", 20))
    surge_n = int(p.get("surge_count", 15))
    ivl = int(p.get("interval_ms", 150))

    _log(f"Seeding {seed_n} normal readings ({baseline} W) on {targets}")
    for i in range(seed_n):
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(active_power=baseline + (i % 5) * 8), label=f"seed {i+1}")
        _ms(ivl)
    _log(f"Injecting {surge_n} surge readings ({surge} W)", "warning")
    for i in range(surge_n):
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(active_power=surge + (i % 3) * 200), label=f"SURGE {i+1}")
        _ms(ivl)
    _log("Power Surge complete")

def _run_voltage_anomaly_ac(p: dict) -> None:
    targets = p.get("targets") or ["load1"]
    voltage = float(p.get("ac_voltage", 295.0))
    count = int(p.get("count", 5))
    ivl = int(p.get("interval_ms", 300))
    _log(f"AC Voltage Anomaly — {voltage} V on {targets} × {count}", "warning")
    for i in range(count):
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(ac_voltage=voltage), label=f"{i+1}")
        _ms(ivl)
    _log("AC Voltage Anomaly complete")

def _run_voltage_anomaly_battery(p: dict) -> None:
    voltage = float(p.get("battery_voltage", 3.1))
    count = int(p.get("count", 5))
    ivl = int(p.get("interval_ms", 300))
    _log(f"Battery Voltage Anomaly — {voltage} V × {count}", "warning")
    for i in range(count):
        pub("ems/battery", make_battery(battery_voltage=voltage), label=f"{i+1}")
        _ms(ivl)
    _log("Battery Voltage Anomaly complete")

def _run_current_surge(p: dict) -> None:
    targets = p.get("targets") or ["load1", "load2", "load3"]
    current = float(p.get("current_a", 30.0))
    count = int(p.get("count", 10))
    ivl = int(p.get("interval_ms", 200))
    _log(f"Current Surge — {current} A on {targets} × {count}", "warning")
    for i in range(count):
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(ac_current=current, active_power=round(current * 230, 1)), label=f"{i+1}")
        _ms(ivl)
    _log("Current Surge complete")

def _run_frequency_deviation(p: dict) -> None:
    targets = p.get("targets") or ["load1", "load2", "load3"]
    normal_hz = float(p.get("normal_hz", 50.0))
    dev_hz = float(p.get("deviated_hz", 44.0))
    seed_n = int(p.get("seed_count", 20))
    dev_n = int(p.get("deviation_count", 15))
    ivl = int(p.get("interval_ms", 200))

    _log(f"Frequency Deviation — seeding {seed_n} @ {normal_hz} Hz")
    for i in range(seed_n):
        freq = normal_hz + random.uniform(-0.05, 0.05)
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(frequency=round(freq, 3)), label=f"seed {i+1}")
        _ms(ivl)
    _log(f"Injecting {dev_n} readings @ {dev_hz} Hz", "warning")
    for i in range(dev_n):
        freq = dev_hz + random.uniform(-0.2, 0.2)
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(frequency=round(freq, 3)), label=f"DEV {i+1}")
        _ms(ivl)
    _log("Frequency Deviation complete")

def _run_power_factor_anomaly(p: dict) -> None:
    targets = p.get("targets") or ["load1", "load2", "load3"]
    pf = float(p.get("pf_value", 0.3))
    count = int(p.get("count", 10))
    ivl = int(p.get("interval_ms", 200))
    _log(f"Power Factor Anomaly — PF={pf} on {targets} × {count}", "warning")
    for i in range(count):
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(power_factor=pf), label=f"{i+1}")
        _ms(ivl)
    _log("Power Factor Anomaly complete")

def _run_battery_soc_crash(p: dict) -> None:
    seed_soc = float(p.get("seed_soc", 85.0))
    crash_soc = float(p.get("crash_soc", 4.0))
    crash_v = float(p.get("crash_voltage", 9.8))
    seed_n = int(p.get("seed_count", 20))
    crash_n = int(p.get("crash_count", 15))
    ivl = int(p.get("interval_ms", 200))

    _log(f"Battery SOC Crash — seeding {seed_n} @ SOC {seed_soc}%")
    for i in range(seed_n):
        pub("ems/battery", make_battery(soc=round(seed_soc + random.uniform(-0.5, 0.5), 2), battery_voltage=12.8), label=f"seed {i+1}")
        _ms(ivl)
    _log(f"Crashing to SOC {crash_soc}% / {crash_v} V", "warning")
    for i in range(crash_n):
        soc = crash_soc + random.uniform(0, 1.5)
        v = crash_v + random.uniform(-0.1, 0.1)
        c = -0.3 + random.uniform(-0.05, 0.05)
        pub("ems/battery", make_battery(soc=round(soc, 2), battery_voltage=round(v, 3),
            battery_current=round(c, 3), battery_power=round(v * c, 3)), label=f"CRASH {i+1}")
        _ms(ivl)
    _log("Battery SOC Crash complete")

def _run_battery_temp_spike(p: dict) -> None:
    temp = float(p.get("temperature", 65.0))
    count = int(p.get("count", 10))
    ivl = int(p.get("interval_ms", 300))
    _log(f"Battery Temperature Spike — {temp}°C × {count}", "warning")
    for i in range(count):
        pub("ems/battery", make_battery(temperature=round(temp + random.uniform(-0.5, 0.5), 2)), label=f"{i+1}")
        _ms(ivl)
    _log("Battery Temperature Spike complete")

def _run_power_spike_ids(p: dict) -> None:
    target = p.get("target", "load3")
    baseline = float(p.get("baseline_w", 2300))
    spike = float(p.get("spike_w", 12000))
    seed_n = int(p.get("seed_count", 20))
    _log(f"Power Spike IDS — seeding {seed_n} @ {baseline} W on {target}")
    for i in range(seed_n):
        pub(f"ems/ac/{target}", make_ac(active_power=baseline + (i % 5) * 10), label=f"seed {i+1}")
        time.sleep(0.1)
    _log(f"Injecting {spike} W spike", "warning")
    pub(f"ems/ac/{target}", make_ac(active_power=spike), label="SPIKE")
    _log("Power Spike IDS complete")

def _run_voltage_trend_ids(p: dict) -> None:
    start_v = float(p.get("start_voltage", 13.5))
    steps = int(p.get("steps", 22))
    decrement = float(p.get("step_decrement", 0.1))
    ivl = int(p.get("interval_ms", 150))
    _log(f"Voltage Trend IDS — {start_v} V declining {steps} steps (−{decrement} V each)")
    for i in range(steps):
        pub("ems/battery", make_battery(battery_voltage=round(start_v - i * decrement, 3)), label=f"step {i+1}")
        _ms(ivl)
    _log("Voltage Trend IDS complete")

def _run_mqtt_flood(p: dict) -> None:
    count = int(p.get("packet_count", 80))
    ivl = int(p.get("interval_ms", 25))
    _log(f"MQTT Flood — {count} packets @ {ivl} ms interval", "warning")
    for i in range(count):
        pub("ems/battery", make_battery(), label=f"{i+1}/{count}")
        _ms(ivl)
    _log("MQTT Flood complete")

def _run_unknown_topic(p: dict) -> None:
    custom_topic = (p.get("custom_topic") or "").strip()
    custom_payload = (p.get("custom_payload") or "").strip()
    if custom_topic:
        try:
            payload: Any = json.loads(custom_payload) if custom_payload else {}
        except Exception:
            payload = custom_payload
        _log(f"Unknown Topic — {custom_topic}", "warning")
        pub(custom_topic, payload, label="CUSTOM")
    else:
        _log("Unknown Topic — publishing on 3 unrecognised topics", "warning")
        for topic, payload in [
            ("ems/admin/config", {"cmd": "set_broker", "host": "attacker.local"}),
            ("sensors/exfil", {"battery_voltage": 12.8, "soc": 85}),
            ("home/lights/bedroom", {"state": "ON"}),
        ]:
            pub(topic, payload)
            time.sleep(0.3)
    _log("Unknown Topic complete")

def _run_malformed_payload(p: dict) -> None:
    target = p.get("target", "battery")
    count = int(p.get("count", 3))
    topic = "ems/battery" if target == "battery" else f"ems/ac/{target}"
    bad = [{}, {"wrong_field": 12.8, "garbage": True}, {"partial": True}]
    _log(f"Malformed Payload — {count} bad payloads → {topic}", "warning")
    for i in range(count):
        pub(topic, bad[i % len(bad)], label=f"malformed {i+1}")
        time.sleep(0.3)
    _log("Malformed Payload complete")

def _run_grid_stress(p: dict) -> None:
    power = float(p.get("power_w", 9000))
    freq = float(p.get("frequency_hz", 44.0))
    crash_soc = float(p.get("crash_soc", 5.0))
    duration_s = int(p.get("duration_s", 10))
    ivl = int(p.get("interval_ms", 500))
    _log(f"Grid Stress — {power} W / {freq} Hz / SOC→{crash_soc}% for {duration_s} s", "warning")
    end = time.time() + duration_s
    i = 0
    while time.time() < end:
        pv = power + random.uniform(-100, 100)
        fv = freq + random.uniform(-0.3, 0.3)
        for lg in ["load1", "load2", "load3"]:
            pub(f"ems/ac/{lg}", make_ac(active_power=round(pv, 1), frequency=round(fv, 3)), label=f"stress {i+1}")
        soc = crash_soc + random.uniform(0, 2)
        pub("ems/battery", make_battery(soc=round(soc, 2), battery_voltage=9.8, battery_current=-0.3), label=f"bat {i+1}")
        _ms(ivl)
        i += 1
    _log("Grid Stress complete")

# ---------------------------------------------------------------------------
# Quick attacks — accept optional params dict (targets list for AC attacks)
# ---------------------------------------------------------------------------
ALL_LOADS = ["load1", "load2", "load3"]

def _q_targets(p: dict, default: list[str] | None = None) -> list[str]:
    t = p.get("targets") or default or ALL_LOADS
    return t if t else (default or ALL_LOADS)

def _quick_mqtt_flood(p: dict = {}) -> None:
    _log("Quick: MQTT Flood (80 packets @ 25 ms)", "warning")
    for i in range(80):
        pub("ems/battery", make_battery(), label=f"{i+1}/80")
        time.sleep(0.025)
    _log("Quick: MQTT Flood complete")

def _quick_unknown_topic(p: dict = {}) -> None:
    _log("Quick: Unknown Topic (3 fake topics)", "warning")
    for topic, payload in [
        ("ems/admin/config", {"cmd": "set_broker", "host": "attacker.local"}),
        ("sensors/exfil", {"battery_voltage": 12.8, "soc": 85}),
        ("home/lights/bedroom", {"state": "ON"}),
    ]:
        pub(topic, payload)
        time.sleep(0.3)
    _log("Quick: Unknown Topic complete")

def _quick_voltage_anomaly(p: dict = {}) -> None:
    targets = _q_targets(p, ["load1"])
    _log(f"Quick: Voltage Anomaly (battery undervoltage + AC overvoltage on {targets})", "warning")
    pub("ems/battery", make_battery(battery_voltage=3.1))
    time.sleep(0.5)
    pub("ems/battery", make_battery(battery_voltage=19.5))
    time.sleep(0.5)
    for lg in targets:
        pub(f"ems/ac/{lg}", make_ac(ac_voltage=295.0), label=lg)
        time.sleep(0.3)
    _log("Quick: Voltage Anomaly complete")

def _quick_malformed(p: dict = {}) -> None:
    targets = _q_targets(p, ["load2"])
    _log(f"Quick: Malformed Payload (battery + {targets})", "warning")
    pub("ems/battery", {})
    time.sleep(0.5)
    pub("ems/battery", {"volt": 12.8, "amp": -3.0})
    time.sleep(0.5)
    for lg in targets:
        pub(f"ems/ac/{lg}", {"ac_voltage": 230.0, "ac_current": 10.0}, label=lg)
        time.sleep(0.3)
    _log("Quick: Malformed Payload complete")

def _quick_power_spike(p: dict = {}) -> None:
    targets = _q_targets(p, ["load3"])
    for target in targets:
        _log(f"Quick: Power Spike IDS — seeding then spiking {target}", "warning")
        for i in range(20):
            pub(f"ems/ac/{target}", make_ac(active_power=float(2300 + (i % 5) * 10)), label=f"seed {i+1}")
            time.sleep(0.1)
        time.sleep(0.3)
        pub(f"ems/ac/{target}", make_ac(active_power=12000.0), label="SPIKE")
        time.sleep(0.5)
    _log("Quick: Power Spike IDS complete")

def _quick_voltage_trend(p: dict = {}) -> None:
    _log("Quick: Voltage Trend IDS (22 declining steps on battery)", "warning")
    for i in range(22):
        pub("ems/battery", make_battery(battery_voltage=round(13.5 - i * 0.1, 3)), label=f"step {i+1}")
        time.sleep(0.15)
    _log("Quick: Voltage Trend IDS complete")

def _quick_power_surge(p: dict = {}) -> None:
    targets = _q_targets(p)
    _log(f"Quick: Power Surge Anomaly (2300 W → 8000 W on {targets})", "warning")
    for i in range(20):
        pw = 2300.0 + (i % 5) * 8
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(active_power=pw), label=f"seed {i+1}")
        time.sleep(0.25)
    for i in range(15):
        sp = 8000.0 + (i % 3) * 200
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(active_power=sp), label=f"SURGE {i+1}")
        time.sleep(0.3)
    _log("Quick: Power Surge Anomaly complete")

def _quick_freq_deviation(p: dict = {}) -> None:
    targets = _q_targets(p)
    _log(f"Quick: Frequency Deviation Anomaly (50 Hz → 44 Hz on {targets})", "warning")
    for i in range(20):
        freq = 50.0 + random.uniform(-0.05, 0.05)
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(frequency=round(freq, 3)), label=f"seed {i+1}")
        time.sleep(0.25)
    for i in range(15):
        freq = 44.0 + random.uniform(-0.2, 0.2)
        for lg in targets:
            pub(f"ems/ac/{lg}", make_ac(frequency=round(freq, 3)), label=f"44Hz {i+1}")
        time.sleep(0.3)
    _log("Quick: Frequency Deviation Anomaly complete")

def _quick_soc_crash(p: dict = {}) -> None:
    _log("Quick: Battery SOC Crash Anomaly (85% → 4% / 9.8 V)", "warning")
    for i in range(20):
        pub("ems/battery", make_battery(soc=round(85.0 + random.uniform(-0.5, 0.5), 2), battery_voltage=12.8), label=f"seed {i+1}")
        time.sleep(0.25)
    for i in range(15):
        soc = 4.0 + random.uniform(0, 1.5)
        v = 9.8 + random.uniform(-0.1, 0.1)
        c = -0.3 + random.uniform(-0.05, 0.05)
        pub("ems/battery", make_battery(soc=round(soc, 2), battery_voltage=round(v, 3),
            battery_current=round(c, 3), battery_power=round(v * c, 3)), label=f"CRASH {i+1}")
        time.sleep(0.3)
    _log("Quick: Battery SOC Crash Anomaly complete")

# ---------------------------------------------------------------------------
# Dispatch tables
# ---------------------------------------------------------------------------
CUSTOM_DISPATCH = {
    "power_surge": _run_power_surge,
    "voltage_anomaly_ac": _run_voltage_anomaly_ac,
    "voltage_anomaly_battery": _run_voltage_anomaly_battery,
    "current_surge": _run_current_surge,
    "frequency_deviation": _run_frequency_deviation,
    "power_factor_anomaly": _run_power_factor_anomaly,
    "battery_soc_crash": _run_battery_soc_crash,
    "battery_temp_spike": _run_battery_temp_spike,
    "power_spike_ids": _run_power_spike_ids,
    "voltage_trend_ids": _run_voltage_trend_ids,
    "mqtt_flood": _run_mqtt_flood,
    "unknown_topic": _run_unknown_topic,
    "malformed_payload": _run_malformed_payload,
    "grid_stress": _run_grid_stress,
}

QUICK_DISPATCH: dict[str, Any] = {
    "mqtt_flood": _quick_mqtt_flood,
    "unknown_topic": _quick_unknown_topic,
    "voltage_anomaly": _quick_voltage_anomaly,
    "malformed": _quick_malformed,
    "power_spike": _quick_power_spike,
    "voltage_trend": _quick_voltage_trend,
    "power_surge": _quick_power_surge,
    "freq_deviation": _quick_freq_deviation,
    "soc_crash": _quick_soc_crash,
}

# ---------------------------------------------------------------------------
# MQTT connection
# ---------------------------------------------------------------------------
def _connect(host: str, port: int) -> str:
    global _client, _connected, _broker_host, _broker_port
    if _client:
        try:
            _client.loop_stop()
            _client.disconnect()
        except Exception:
            pass
    _broker_host, _broker_port, _connected = host, port, False

    def on_connect(c, _ud, _flags, rc):
        global _connected
        _connected = rc == 0
        _log(f"Connected to {host}:{port}" if _connected else f"Connect failed rc={rc}",
             "info" if _connected else "error")

    def on_disconnect(c, _ud, rc):
        global _connected
        _connected = False
        _log(f"Disconnected (rc={rc})", "warning")

    c = mqtt.Client()
    c.on_connect = on_connect
    c.on_disconnect = on_disconnect
    try:
        c.connect(host, port, keepalive=60)
        c.loop_start()
        _client = c
        time.sleep(0.6)
        return "ok" if _connected else "connecting"
    except Exception as e:
        _log(f"Connection error: {e}", "error")
        return f"error: {e}"

# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------
app = FastAPI(title="EMS Attack Simulator UI", docs_url=None, redoc_url=None)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

class ConnectRequest(BaseModel):
    host: str
    port: int = 1883

class AttackRequest(BaseModel):
    type: str
    params: dict = {}

class QuickAttackRequest(BaseModel):
    name: str
    params: dict = {}

@app.post("/api/connect")
def api_connect(body: ConnectRequest):
    result = _connect(body.host, body.port)
    return {"result": result, "connected": _connected}

@app.get("/api/status")
def api_status():
    return {"connected": _connected, "broker": f"{_broker_host}:{_broker_port}",
            "running": _running_attack, "log_count": len(_log_queue)}

@app.get("/api/log")
def api_log(since: int = 0):
    entries = list(_log_queue)
    return {"entries": entries[since:], "total": len(_log_queue)}

@app.post("/api/attack/custom")
def api_custom_attack(body: AttackRequest):
    global _running_attack
    if _running_attack:
        return JSONResponse({"error": f"'{_running_attack}' already running"}, status_code=409)
    fn = CUSTOM_DISPATCH.get(body.type)
    if not fn:
        return JSONResponse({"error": f"Unknown: {body.type}"}, status_code=400)
    if not _connected:
        return JSONResponse({"error": "Not connected to MQTT broker"}, status_code=503)
    def run():
        global _running_attack
        _running_attack = body.type
        try:
            fn(body.params)
        except Exception as e:
            _log(f"Attack error: {e}", "error")
        finally:
            _running_attack = None
    threading.Thread(target=run, daemon=True).start()
    return {"started": body.type}

@app.post("/api/attack/quick")
def api_quick_attack(body: QuickAttackRequest):
    global _running_attack
    if _running_attack:
        return JSONResponse({"error": f"'{_running_attack}' already running"}, status_code=409)
    fn = QUICK_DISPATCH.get(body.name)
    if not fn:
        return JSONResponse({"error": f"Unknown: {body.name}"}, status_code=400)
    if not _connected:
        return JSONResponse({"error": "Not connected to MQTT broker"}, status_code=503)
    def run():
        global _running_attack
        _running_attack = body.name
        try:
            fn(body.params)
        except Exception as e:
            _log(f"Attack error: {e}", "error")
        finally:
            _running_attack = None
    threading.Thread(target=run, daemon=True).start()
    return {"started": body.name}

@app.get("/", response_class=HTMLResponse)
def index():
    return HTML_PAGE

# ---------------------------------------------------------------------------
# HTML — embedded
# ---------------------------------------------------------------------------
HTML_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EMS Attack Simulator</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d1017;color:#c9d1d9;font-family:system-ui,-apple-system,sans-serif;font-size:14px;min-height:100vh}
a{color:inherit}
/* Layout */
.topbar{display:flex;align-items:center;justify-content:space-between;padding:14px 24px;background:#161b22;border-bottom:1px solid #21262d;gap:12px;flex-wrap:wrap}
.topbar h1{font-size:16px;font-weight:700;color:#f0f6fc;display:flex;align-items:center;gap:8px}
.topbar h1 span{font-size:20px}
.broker-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
.broker-row input{background:#0d1017;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:6px 10px;font-size:13px;width:160px}
.broker-row input[type=number]{width:76px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:6px 14px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;transition:opacity .15s}
.btn:disabled{opacity:.4;cursor:default}
.btn-primary{background:#f59e0b;color:#000}
.btn-primary:hover:not(:disabled){opacity:.85}
.btn-danger{background:#ef4444;color:#fff}
.btn-danger:hover:not(:disabled){opacity:.85}
.btn-ghost{background:#21262d;color:#c9d1d9;border:1px solid #30363d}
.btn-ghost:hover:not(:disabled){background:#30363d}
.btn-sm{padding:4px 10px;font-size:12px}
.led{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:4px;flex-shrink:0}
.led.on{background:#22c55e;box-shadow:0 0 6px #22c55e}
.led.off{background:#4b5563}
.status-txt{font-size:12px;color:#8b949e}
/* Main grid */
.main{display:grid;grid-template-columns:1fr 340px;gap:16px;padding:16px 24px;align-items:start}
@media(max-width:900px){.main{grid-template-columns:1fr}}
/* Cards */
.card{background:#161b22;border:1px solid #21262d;border-radius:10px;padding:18px}
.card-title{font-size:13px;font-weight:700;color:#f0f6fc;margin-bottom:14px;display:flex;align-items:center;gap:6px}
.card-title .badge{font-size:10px;font-weight:600;padding:2px 7px;border-radius:20px;background:#f59e0b22;color:#f59e0b}
/* Form elements */
label{display:block;font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px;margin-top:10px}
label:first-child{margin-top:0}
select,input[type=text],input[type=number],textarea{width:100%;background:#0d1017;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:7px 10px;font-size:13px;outline:none;transition:border-color .15s}
select:focus,input:focus,textarea:focus{border-color:#f59e0b}
textarea{resize:vertical;min-height:64px;font-family:monospace}
.range-row{display:flex;align-items:center;gap:10px}
input[type=range]{flex:1;accent-color:#f59e0b}
.range-val{font-size:12px;color:#f59e0b;min-width:52px;text-align:right}
/* Checkboxes */
.check-group{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px}
.check-item{display:flex;align-items:center;gap:5px;padding:5px 10px;background:#0d1017;border:1px solid #30363d;border-radius:6px;cursor:pointer;font-size:12px;transition:border-color .15s}
.check-item:hover{border-color:#f59e0b}
.check-item input{accent-color:#f59e0b;width:14px;height:14px}
.check-item.checked{border-color:#f59e0b;background:#f59e0b12}
/* Params sections */
.attack-params{display:none;border-top:1px solid #21262d;padding-top:14px;margin-top:14px;flex-direction:column;gap:2px}
.attack-params.active{display:flex}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px}
/* Quick attacks */
.quick-section{margin-bottom:14px}
.quick-section h3{font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:.06em;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #21262d}
.quick-grid{display:flex;flex-direction:column;gap:6px}
.quick-btn{width:100%;text-align:left;padding:9px 12px;background:#0d1017;border:1px solid #21262d;border-radius:8px;color:#c9d1d9;cursor:pointer;transition:border-color .15s,background .15s;display:flex;justify-content:space-between;align-items:center}
.quick-btn:hover{border-color:#f59e0b;background:#f59e0b0a}
.quick-btn:disabled{opacity:.4;cursor:default}
.quick-btn .q-name{font-size:13px;font-weight:600}
.quick-btn .q-tag{font-size:10px;padding:2px 7px;border-radius:20px;font-weight:600}
.tag-ids{background:#ef444420;color:#ef4444}
.tag-anomaly{background:#a855f720;color:#a855f7}
/* Log */
.log-wrap{padding:0 24px 24px}
.log-header{display:flex;align-items:center;gap:10px;margin-bottom:8px}
.log-header h2{font-size:13px;font-weight:700;color:#f0f6fc}
.log-count{font-size:11px;padding:2px 7px;background:#21262d;border-radius:20px;color:#8b949e}
.log-box{background:#0d1017;border:1px solid #21262d;border-radius:8px;height:220px;overflow-y:auto;padding:10px 14px;font-family:monospace;font-size:12px;display:flex;flex-direction:column;gap:3px}
.log-entry{display:flex;gap:8px;line-height:1.5}
.log-ts{color:#4b5563;flex-shrink:0;width:90px}
.log-level-info .log-msg{color:#c9d1d9}
.log-level-warning .log-msg{color:#f59e0b}
.log-level-error .log-msg{color:#ef4444}
.log-topic{color:#60a5fa;font-size:11px}
.log-payload{color:#4b5563;font-size:11px}
.running-bar{display:none;align-items:center;gap:8px;padding:8px 14px;background:#f59e0b12;border:1px solid #f59e0b30;border-radius:8px;margin-bottom:12px;font-size:12px;color:#f59e0b}
.running-bar.active{display:flex}
@keyframes spin{to{transform:rotate(360deg)}}
.spinner{width:14px;height:14px;border:2px solid #f59e0b40;border-top-color:#f59e0b;border-radius:50%;animation:spin .8s linear infinite;flex-shrink:0}
/* Attack type selector */
#attack-select{margin-bottom:0}
.desc{font-size:12px;color:#8b949e;margin-top:6px;line-height:1.5;padding:8px 10px;background:#0d1017;border-radius:6px;border-left:3px solid #f59e0b}
</style>
</head>
<body>

<!-- Top bar -->
<div class="topbar">
  <h1><span>⚡</span> EMS Attack Simulator</h1>
  <div class="broker-row">
    <input id="broker-host" value="192.168.1.130" placeholder="Broker host">
    <input id="broker-port" type="number" value="1883" placeholder="Port">
    <button class="btn btn-primary" onclick="connect()">Connect</button>
    <span class="led off" id="status-led"></span>
    <span class="status-txt" id="status-txt">Disconnected</span>
  </div>
</div>

<!-- Main grid -->
<div class="main">

  <!-- LEFT: Custom Attack Builder -->
  <div class="card">
    <div class="card-title">Custom Attack Builder <span class="badge">14 attack types</span></div>

    <div class="running-bar" id="running-bar">
      <div class="spinner"></div>
      <span id="running-txt">Attack running…</span>
      <span style="margin-left:auto;font-size:11px;color:#8b949e">Wait for it to complete before launching another</span>
    </div>

    <label>Attack Type</label>
    <select id="attack-select" onchange="onAttackChange()">
      <option value="">— Select an attack —</option>
      <optgroup label="Anomaly Monitor (statistical / ML detection, ~10 s lag)">
        <option value="power_surge">Power Surge — AC load active power spike</option>
        <option value="current_surge">Current Surge — AC load overcurrent</option>
        <option value="frequency_deviation">Frequency Deviation — grid instability</option>
        <option value="power_factor_anomaly">Power Factor Anomaly — capacitive/inductive fault</option>
        <option value="voltage_anomaly_ac">AC Voltage Anomaly — overvoltage / sag</option>
        <option value="battery_soc_crash">Battery SOC Crash — rapid drain</option>
        <option value="voltage_anomaly_battery">Battery Voltage Anomaly — under/overvoltage</option>
        <option value="battery_temp_spike">Battery Temperature Spike — thermal event</option>
        <option value="grid_stress">Full Grid Stress — all signals simultaneously</option>
      </optgroup>
      <optgroup label="IDS Alerts (trigger immediately, no lag)">
        <option value="power_spike_ids">Power Spike — z-score IDS rule</option>
        <option value="voltage_trend_ids">Voltage Trend — consecutive decline IDS rule</option>
        <option value="mqtt_flood">MQTT Flood — packet rate IDS rule</option>
        <option value="unknown_topic">Unknown Topic Injection</option>
        <option value="malformed_payload">Malformed Payload</option>
      </optgroup>
    </select>

    <div id="attack-desc" class="desc" style="display:none"></div>

    <!-- ── power_surge ── -->
    <div class="attack-params" id="params-power_surge">
      <label>Target Load Groups</label>
      <div class="check-group" id="cg-power_surge-targets">
        <label class="check-item checked"><input type="checkbox" name="targets" value="load1" checked onchange="syncCheck(this)"> Load 1</label>
        <label class="check-item checked"><input type="checkbox" name="targets" value="load2" checked onchange="syncCheck(this)"> Load 2</label>
        <label class="check-item checked"><input type="checkbox" name="targets" value="load3" checked onchange="syncCheck(this)"> Load 3</label>
      </div>
      <div class="grid2">
        <div><label>Baseline Power (W)</label><input type="number" name="baseline_w" value="2300" min="0" max="10000"></div>
        <div><label>Surge Power (W)</label><input type="number" name="surge_w" value="8000" min="100" max="25000"></div>
        <div><label>Seed Packets</label><input type="number" name="seed_count" value="20" min="5" max="60"></div>
        <div><label>Surge Packets</label><input type="number" name="surge_count" value="15" min="5" max="60"></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="150" oninput="rv(this)"><span class="range-val">150 ms</span></div>
    </div>

    <!-- ── voltage_anomaly_ac ── -->
    <div class="attack-params" id="params-voltage_anomaly_ac">
      <label>Target Load Groups</label>
      <div class="check-group">
        <label class="check-item checked"><input type="checkbox" name="targets" value="load1" checked onchange="syncCheck(this)"> Load 1</label>
        <label class="check-item"><input type="checkbox" name="targets" value="load2" onchange="syncCheck(this)"> Load 2</label>
        <label class="check-item"><input type="checkbox" name="targets" value="load3" onchange="syncCheck(this)"> Load 3</label>
      </div>
      <div class="grid2">
        <div><label>AC Voltage (V)</label><input type="number" name="ac_voltage" value="295" min="0" max="600" step="0.1"></div>
        <div><label>Repeat Count</label><input type="number" name="count" value="5" min="1" max="50"></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="300" oninput="rv(this)"><span class="range-val">300 ms</span></div>
    </div>

    <!-- ── voltage_anomaly_battery ── -->
    <div class="attack-params" id="params-voltage_anomaly_battery">
      <div class="grid2">
        <div><label>Battery Voltage (V)</label><input type="number" name="battery_voltage" value="3.1" min="0" max="20" step="0.1"></div>
        <div><label>Repeat Count</label><input type="number" name="count" value="5" min="1" max="50"></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="300" oninput="rv(this)"><span class="range-val">300 ms</span></div>
    </div>

    <!-- ── current_surge ── -->
    <div class="attack-params" id="params-current_surge">
      <label>Target Load Groups</label>
      <div class="check-group">
        <label class="check-item checked"><input type="checkbox" name="targets" value="load1" checked onchange="syncCheck(this)"> Load 1</label>
        <label class="check-item checked"><input type="checkbox" name="targets" value="load2" checked onchange="syncCheck(this)"> Load 2</label>
        <label class="check-item checked"><input type="checkbox" name="targets" value="load3" checked onchange="syncCheck(this)"> Load 3</label>
      </div>
      <div class="grid2">
        <div><label>Current (A)</label><input type="number" name="current_a" value="30" min="0" max="200" step="0.5"></div>
        <div><label>Repeat Count</label><input type="number" name="count" value="10" min="1" max="60"></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="200" oninput="rv(this)"><span class="range-val">200 ms</span></div>
    </div>

    <!-- ── frequency_deviation ── -->
    <div class="attack-params" id="params-frequency_deviation">
      <label>Target Load Groups</label>
      <div class="check-group">
        <label class="check-item checked"><input type="checkbox" name="targets" value="load1" checked onchange="syncCheck(this)"> Load 1</label>
        <label class="check-item checked"><input type="checkbox" name="targets" value="load2" checked onchange="syncCheck(this)"> Load 2</label>
        <label class="check-item checked"><input type="checkbox" name="targets" value="load3" checked onchange="syncCheck(this)"> Load 3</label>
      </div>
      <div class="grid2">
        <div><label>Normal Frequency (Hz)</label><input type="number" name="normal_hz" value="50" min="40" max="70" step="0.1"></div>
        <div><label>Deviated Frequency (Hz)</label><input type="number" name="deviated_hz" value="44" min="30" max="70" step="0.1"></div>
        <div><label>Seed Packets</label><input type="number" name="seed_count" value="20" min="5" max="60"></div>
        <div><label>Deviation Packets</label><input type="number" name="deviation_count" value="15" min="5" max="60"></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="200" oninput="rv(this)"><span class="range-val">200 ms</span></div>
    </div>

    <!-- ── power_factor_anomaly ── -->
    <div class="attack-params" id="params-power_factor_anomaly">
      <label>Target Load Groups</label>
      <div class="check-group">
        <label class="check-item checked"><input type="checkbox" name="targets" value="load1" checked onchange="syncCheck(this)"> Load 1</label>
        <label class="check-item checked"><input type="checkbox" name="targets" value="load2" checked onchange="syncCheck(this)"> Load 2</label>
        <label class="check-item checked"><input type="checkbox" name="targets" value="load3" checked onchange="syncCheck(this)"> Load 3</label>
      </div>
      <label>Power Factor (0–1)</label>
      <div class="range-row"><input type="range" name="pf_value" min="0" max="1" step="0.01" value="0.3" oninput="rv(this)"><span class="range-val">0.3</span></div>
      <div class="grid2">
        <div><label>Repeat Count</label><input type="number" name="count" value="10" min="1" max="60"></div>
        <div></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="200" oninput="rv(this)"><span class="range-val">200 ms</span></div>
    </div>

    <!-- ── battery_soc_crash ── -->
    <div class="attack-params" id="params-battery_soc_crash">
      <div class="grid2">
        <div><label>Seed SOC (%)</label><input type="number" name="seed_soc" value="85" min="50" max="100"></div>
        <div><label>Crash SOC (%)</label><input type="number" name="crash_soc" value="4" min="0" max="30"></div>
        <div><label>Crash Voltage (V)</label><input type="number" name="crash_voltage" value="9.8" min="5" max="13" step="0.1"></div>
        <div></div>
        <div><label>Seed Packets</label><input type="number" name="seed_count" value="20" min="5" max="60"></div>
        <div><label>Crash Packets</label><input type="number" name="crash_count" value="15" min="5" max="60"></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="200" oninput="rv(this)"><span class="range-val">200 ms</span></div>
    </div>

    <!-- ── battery_temp_spike ── -->
    <div class="attack-params" id="params-battery_temp_spike">
      <label>Temperature (°C)</label>
      <div class="range-row"><input type="range" name="temperature" min="30" max="100" value="65" oninput="rv(this)"><span class="range-val">65 °C</span></div>
      <div class="grid2">
        <div><label>Repeat Count</label><input type="number" name="count" value="10" min="1" max="60"></div>
        <div></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="300" oninput="rv(this)"><span class="range-val">300 ms</span></div>
    </div>

    <!-- ── power_spike_ids ── -->
    <div class="attack-params" id="params-power_spike_ids">
      <label>Target Load Group</label>
      <select name="target"><option value="load1">Load 1</option><option value="load2">Load 2</option><option value="load3" selected>Load 3</option></select>
      <div class="grid2">
        <div><label>Baseline Power (W)</label><input type="number" name="baseline_w" value="2300" min="0" max="10000"></div>
        <div><label>Spike Power (W)</label><input type="number" name="spike_w" value="12000" min="100" max="50000"></div>
        <div><label>Seed Packets</label><input type="number" name="seed_count" value="20" min="5" max="60"></div>
        <div></div>
      </div>
    </div>

    <!-- ── voltage_trend_ids ── -->
    <div class="attack-params" id="params-voltage_trend_ids">
      <div class="grid3">
        <div><label>Start Voltage (V)</label><input type="number" name="start_voltage" value="13.5" min="10" max="16" step="0.1"></div>
        <div><label>Steps</label><input type="number" name="steps" value="22" min="5" max="50"></div>
        <div><label>Decrement (V)</label><input type="number" name="step_decrement" value="0.1" min="0.01" max="0.5" step="0.01"></div>
      </div>
      <label>Step Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="50" max="2000" value="150" oninput="rv(this)"><span class="range-val">150 ms</span></div>
    </div>

    <!-- ── mqtt_flood ── -->
    <div class="attack-params" id="params-mqtt_flood">
      <div class="grid2">
        <div><label>Packet Count</label><input type="number" name="packet_count" value="80" min="10" max="500"></div>
        <div></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="5" max="500" value="25" oninput="rv(this)"><span class="range-val">25 ms</span></div>
    </div>

    <!-- ── unknown_topic ── -->
    <div class="attack-params" id="params-unknown_topic">
      <label>Custom Topic (leave blank to use 3 default fake topics)</label>
      <input type="text" name="custom_topic" placeholder="e.g. ems/admin/secret">
      <label>Payload (JSON)</label>
      <textarea name="custom_payload" placeholder='{"cmd":"exfiltrate"}'></textarea>
    </div>

    <!-- ── malformed_payload ── -->
    <div class="attack-params" id="params-malformed_payload">
      <label>Target</label>
      <select name="target">
        <option value="battery">Battery</option>
        <option value="load1">Load 1</option>
        <option value="load2">Load 2</option>
        <option value="load3">Load 3</option>
      </select>
      <div class="grid2">
        <div><label>Repeat Count</label><input type="number" name="count" value="3" min="1" max="20"></div>
        <div></div>
      </div>
    </div>

    <!-- ── grid_stress ── -->
    <div class="attack-params" id="params-grid_stress">
      <div class="grid2">
        <div><label>Surge Power (W)</label><input type="number" name="power_w" value="9000" min="1000" max="25000"></div>
        <div><label>Deviated Freq (Hz)</label><input type="number" name="frequency_hz" value="44" min="30" max="70" step="0.1"></div>
        <div><label>Crash SOC (%)</label><input type="number" name="crash_soc" value="5" min="0" max="20"></div>
        <div><label>Duration (s)</label><input type="number" name="duration_s" value="10" min="3" max="120"></div>
      </div>
      <label>Packet Interval</label>
      <div class="range-row"><input type="range" name="interval_ms" min="100" max="3000" value="500" oninput="rv(this)"><span class="range-val">500 ms</span></div>
    </div>

    <div style="margin-top:16px">
      <button class="btn btn-danger" id="run-btn" disabled onclick="runCustom()">▶ Run Attack</button>
    </div>
  </div>

  <!-- RIGHT: Quick Attacks -->
  <div style="display:flex;flex-direction:column;gap:16px">
    <div class="card">
      <div class="card-title">Quick Attacks</div>

      <!-- Load group selector for quick attacks -->
      <div style="margin-bottom:14px;padding:10px 12px;background:#0d1017;border:1px solid #21262d;border-radius:8px">
        <div style="font-size:11px;color:#8b949e;text-transform:uppercase;letter-spacing:.05em;margin-bottom:8px">AC Load Targets</div>
        <div style="display:flex;gap:6px">
          <label class="check-item checked" style="flex:1;justify-content:center"><input type="checkbox" id="ql1" value="load1" checked onchange="syncCheck(this)"> L1</label>
          <label class="check-item checked" style="flex:1;justify-content:center"><input type="checkbox" id="ql2" value="load2" checked onchange="syncCheck(this)"> L2</label>
          <label class="check-item checked" style="flex:1;justify-content:center"><input type="checkbox" id="ql3" value="load3" checked onchange="syncCheck(this)"> L3</label>
        </div>
        <div style="font-size:11px;color:#4b5563;margin-top:6px">Applies to attacks that target AC loads. Battery-only attacks ignore this.</div>
      </div>

      <div class="quick-section">
        <h3>IDS Alerts — fire immediately</h3>
        <div class="quick-grid">
          <button class="quick-btn" onclick="runQuick('mqtt_flood')"><span class="q-name">MQTT Flood</span><span class="q-tag tag-ids">IDS</span></button>
          <button class="quick-btn" onclick="runQuick('unknown_topic')"><span class="q-name">Unknown Topic</span><span class="q-tag tag-ids">IDS</span></button>
          <button class="quick-btn" onclick="runQuick('voltage_anomaly')"><span class="q-name">Voltage Anomaly</span><span class="q-tag tag-ids">IDS</span></button>
          <button class="quick-btn" onclick="runQuick('malformed')"><span class="q-name">Malformed Payload</span><span class="q-tag tag-ids">IDS</span></button>
          <button class="quick-btn" onclick="runQuick('power_spike')"><span class="q-name">Power Spike</span><span class="q-tag tag-ids">IDS</span></button>
          <button class="quick-btn" onclick="runQuick('voltage_trend')"><span class="q-name">Voltage Trend</span><span class="q-tag tag-ids">IDS</span></button>
        </div>
      </div>
      <div class="quick-section">
        <h3>Anomaly Monitor — ~10 s lag</h3>
        <div class="quick-grid">
          <button class="quick-btn" onclick="runQuick('power_surge')"><span class="q-name">Power Surge</span><span class="q-tag tag-anomaly">ANOMALY</span></button>
          <button class="quick-btn" onclick="runQuick('freq_deviation')"><span class="q-name">Frequency Deviation</span><span class="q-tag tag-anomaly">ANOMALY</span></button>
          <button class="quick-btn" onclick="runQuick('soc_crash')"><span class="q-name">Battery SOC Crash</span><span class="q-tag tag-anomaly">ANOMALY</span></button>
        </div>
      </div>
    </div>

    <div class="card" style="font-size:12px;color:#8b949e;line-height:1.7">
      <div class="card-title">Usage Notes</div>
      <b style="color:#f0f6fc">IDS attacks</b> trigger immediately on every MQTT message.<br>
      <b style="color:#f0f6fc">Anomaly attacks</b> need 20 seed packets first — detection fires after the inference engine's next 5 s cycle.<br>
      <b style="color:#f0f6fc">Grid Stress</b> hammers all signals simultaneously for the configured duration.<br><br>
      Only one attack can run at a time. The log shows every published packet.
    </div>
  </div>
</div>

<!-- Log -->
<div class="log-wrap">
  <div class="log-header">
    <h2>Activity Log</h2>
    <span class="log-count" id="log-count">0</span>
    <button class="btn btn-ghost btn-sm" onclick="clearLog()" style="margin-left:auto">Clear</button>
    <button class="btn btn-ghost btn-sm" onclick="exportLog()">Export</button>
  </div>
  <div class="log-box" id="log-box"></div>
</div>

<script>
const DESCRIPTIONS = {
  power_surge: "Seeds normal baseline power on selected loads, then injects a sustained surge. Triggers statistical anomaly detection (~10 s lag via inference engine).",
  voltage_anomaly_ac: "Publishes out-of-range AC voltage readings. Triggers the IDS VoltageAnomalyRule immediately.",
  voltage_anomaly_battery: "Publishes out-of-range battery voltage (e.g. 3.1 V or 19.5 V). Triggers IDS immediately.",
  current_surge: "Publishes abnormally high AC current with proportional power. Detected by anomaly monitor.",
  frequency_deviation: "Seeds normal 50 Hz baseline then sustains a deviated frequency (e.g. 44 Hz). Triggers anomaly monitor.",
  power_factor_anomaly: "Publishes a very low power factor — simulates a capacitive or inductive fault. Anomaly monitor.",
  battery_soc_crash: "Seeds normal SOC (~85%) then crashes to a critically low value. Triggers anomaly monitor on SOC + voltage signals.",
  battery_temp_spike: "Publishes abnormally high battery temperature — simulates a thermal runaway event. Anomaly monitor.",
  grid_stress: "Simultaneously stresses all three load groups AND the battery for the configured duration. Most comprehensive test.",
  power_spike_ids: "Seeds a stable power baseline on one load, then sends a single large spike. Triggers IDS PowerSpikeRule (z-score > 4).",
  voltage_trend_ids: "Sends strictly decreasing battery voltages. After 20 consecutive drops, triggers IDS VoltageTrendRule.",
  mqtt_flood: "Floods the broker with many packets in a short window. Triggers IDS MQTTFloodRule (> 60 pkts / 5 s).",
  unknown_topic: "Publishes on topics the backend doesn't recognise. Triggers IDS UnknownTopicRule for each.",
  malformed_payload: "Sends payloads with missing required fields. Triggers IDS MalformedPayloadRule.",
};

let logOffset = 0;

function rv(el) {
  const sib = el.nextElementSibling;
  let unit = '';
  if (el.name === 'pf_value') unit = '';
  else if (el.name === 'temperature') unit = ' °C';
  else unit = ' ms';
  if (sib) sib.textContent = el.value + unit;
}

function syncCheck(cb) {
  const item = cb.closest('.check-item');
  if (cb.checked) item.classList.add('checked');
  else item.classList.remove('checked');
}

function onAttackChange() {
  const type = document.getElementById('attack-select').value;
  document.querySelectorAll('.attack-params').forEach(el => el.classList.remove('active'));
  const desc = document.getElementById('attack-desc');
  if (type) {
    const p = document.getElementById('params-' + type);
    if (p) p.classList.add('active');
    desc.style.display = 'block';
    desc.textContent = DESCRIPTIONS[type] || '';
  } else {
    desc.style.display = 'none';
  }
  document.getElementById('run-btn').disabled = !type;
}

function collectParams(type) {
  const container = document.getElementById('params-' + type);
  if (!container) return {};
  const params = {};
  container.querySelectorAll('input[type=checkbox]').forEach(cb => {
    if (!params[cb.name]) params[cb.name] = [];
    if (cb.checked) params[cb.name].push(cb.value);
  });
  container.querySelectorAll('input[type=number]').forEach(el => {
    if (el.name) params[el.name] = parseFloat(el.value);
  });
  container.querySelectorAll('input[type=range]').forEach(el => {
    if (el.name) params[el.name] = parseFloat(el.value);
  });
  container.querySelectorAll('select').forEach(el => {
    if (el.name) params[el.name] = el.value;
  });
  container.querySelectorAll('input[type=text], textarea').forEach(el => {
    if (el.name) params[el.name] = el.value;
  });
  return params;
}

function runCustom() {
  const type = document.getElementById('attack-select').value;
  if (!type) return;
  const params = collectParams(type);
  fetch('/api/attack/custom', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({type, params})
  }).then(r => r.json()).then(data => {
    if (data.error) appendLog({ts: now(), level: 'error', msg: 'ERROR: ' + data.error, topic: '', payload: ''});
  }).catch(err => appendLog({ts: now(), level: 'error', msg: 'Request failed: ' + err, topic: '', payload: ''}));
}

function getQuickTargets() {
  const t = [];
  ['ql1','ql2','ql3'].forEach(id => { const el = document.getElementById(id); if (el && el.checked) t.push(el.value); });
  return t.length ? t : ['load1','load2','load3'];
}

function runQuick(name) {
  const targets = getQuickTargets();
  fetch('/api/attack/quick', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({name, params: {targets}})
  }).then(r => r.json()).then(data => {
    if (data.error) appendLog({ts: now(), level: 'error', msg: 'ERROR: ' + data.error, topic: '', payload: ''});
  }).catch(err => appendLog({ts: now(), level: 'error', msg: 'Request failed: ' + err, topic: '', payload: ''}));
}

function connect() {
  const host = document.getElementById('broker-host').value.trim();
  const port = parseInt(document.getElementById('broker-port').value);
  fetch('/api/connect', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({host, port})
  }).then(r => r.json()).then(updateStatus).catch(() => {});
}

function pollStatus() {
  fetch('/api/status').then(r => r.json()).then(updateStatus).catch(() => {});
}

function updateStatus(s) {
  const led = document.getElementById('status-led');
  const txt = document.getElementById('status-txt');
  const runBar = document.getElementById('running-bar');
  const runTxt = document.getElementById('running-txt');
  const runBtn = document.getElementById('run-btn');
  const type = document.getElementById('attack-select').value;

  led.className = 'led ' + (s.connected ? 'on' : 'off');
  txt.textContent = s.connected ? `Connected — ${s.broker}` : 'Disconnected';

  if (s.running) {
    runBar.classList.add('active');
    runTxt.textContent = `Running: ${s.running}…`;
    runBtn.disabled = true;
    document.querySelectorAll('.quick-btn').forEach(b => b.disabled = true);
  } else {
    runBar.classList.remove('active');
    runBtn.disabled = !s.connected || !type;
    document.querySelectorAll('.quick-btn').forEach(b => b.disabled = !s.connected);
  }
}

function pollLog() {
  fetch('/api/log?since=' + logOffset)
    .then(r => r.json())
    .then(data => {
      if (data.entries.length) {
        data.entries.forEach(appendLog);
        logOffset = data.total;
        document.getElementById('log-count').textContent = data.total;
      }
    }).catch(() => {});
}

function appendLog(e) {
  const box = document.getElementById('log-box');
  const div = document.createElement('div');
  div.className = 'log-entry log-level-' + e.level;
  div.innerHTML =
    `<span class="log-ts">${e.ts}</span>` +
    `<span class="log-msg">${esc(e.msg)}</span>` +
    (e.topic ? ` <span class="log-topic">${esc(e.topic)}</span>` : '') +
    (e.payload ? ` <span class="log-payload">${esc(e.payload)}</span>` : '');
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function clearLog() {
  document.getElementById('log-box').innerHTML = '';
  logOffset = 0;
  document.getElementById('log-count').textContent = '0';
}

function exportLog() {
  fetch('/api/log?since=0').then(r => r.json()).then(data => {
    const lines = data.entries.map(e => `[${e.ts}] [${e.level.toUpperCase()}] ${e.msg}${e.topic ? ' | ' + e.topic : ''}${e.payload ? ' | ' + e.payload : ''}`);
    const blob = new Blob([lines.join('\\n')], {type: 'text/plain'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'attack_log_' + new Date().toISOString().slice(0,19).replace(/:/g,'-') + '.txt';
    a.click();
  });
}

function now() { return new Date().toTimeString().slice(0,12); }
function esc(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

setInterval(pollStatus, 600);
setInterval(pollLog, 600);
pollStatus();
pollLog();
</script>
</body>
</html>"""

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="EMS Attack Simulator — Web UI")
    parser.add_argument("--broker", default="192.168.1.130", help="MQTT broker host")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--ui-port", type=int, default=7000, help="Web UI port (default: 7000)")
    args = parser.parse_args()

    print(f"\n  EMS Attack Simulator — Web UI")
    print(f"  Connecting to MQTT broker {args.broker}:{args.mqtt_port}…")
    result = _connect(args.broker, args.mqtt_port)
    print(f"  Broker status: {result}")
    print(f"\n  Open http://localhost:{args.ui_port} in your browser\n")
    uvicorn.run(app, host="0.0.0.0", port=args.ui_port, log_level="warning")

if __name__ == "__main__":
    main()
