from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import dataclasses

import aiomqtt
import ids as ids_engine
from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ems")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MQTT_BROKER = "localhost"
MQTT_PORT = 1883

LOAD_GROUPS = ["load1", "load2", "load3"]

TOPICS: dict[str, str] = {"battery": "ems/battery"}
for lg in LOAD_GROUPS:
    TOPICS[lg] = f"ems/ac/{lg}"

STATUS_TOPICS: dict[str, str] = {lg: f"ems/status/{lg}" for lg in LOAD_GROUPS}

# In-memory history buffer size (sent to new WebSocket clients on connect)
HISTORY_SIZE = 120

# Log directory — one CSV per sensor per day
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# CSV column order (must match the JSON keys from ESP32 / mock publisher)
BATTERY_COLUMNS = [
    "timestamp", "time", "battery_voltage", "battery_current",
    "battery_power", "soc", "consumed_ah", "time_to_go",
    "alarm_flags", "temperature",
]

AC_COLUMNS = [
    "timestamp", "date", "time", "ac_voltage", "ac_current",
    "active_power", "active_energy", "frequency", "power_factor",
]

CSV_COLUMNS: dict[str, list[str]] = {"battery": BATTERY_COLUMNS}
for lg in LOAD_GROUPS:
    CSV_COLUMNS[lg] = AC_COLUMNS

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Smart Grid EMS Backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Shared state — one entry per sensor key (battery, load1, load2, load3)
ALL_KEYS = ["battery"] + LOAD_GROUPS

latest: dict[str, dict | None] = {k: None for k in ALL_KEYS}
last_seen: dict[str, str | None] = {k: None for k in ALL_KEYS}
history: dict[str, deque[dict]] = {k: deque(maxlen=HISTORY_SIZE) for k in ALL_KEYS}
mqtt_connected = False

# Shared MQTT client reference — set while the listener is connected
_mqtt_client: aiomqtt.Client | None = None

# Control state — populated from ems/status/{lg} published by the ESP on startup.
# Until the ESP reports in, we have no state (None signals "unknown").
control_state: dict[str, dict] = {
    lg: {
        "relay":     None,
        "threshold": None,
        "on_time":   None,
        "off_time":  None,
        "priority":  None,
    }
    for lg in LOAD_GROUPS
}

# Per-client queues for pushing alerts over WebSocket
_alert_queues: list[asyncio.Queue] = []


async def _dispatch_alert(alert: ids_engine.Alert) -> None:
    for q in _alert_queues:
        await q.put(alert)


# Track open CSV file handles so we rotate daily
_csv_writers: dict[str, tuple[str, csv.writer, object]] = {}

# ---------------------------------------------------------------------------
# CSV data logger
# ---------------------------------------------------------------------------

def _get_csv_writer(sensor: str) -> csv.writer:
    """Return a CSV writer for today's log file, rotating daily."""
    today = datetime.now().strftime("%Y-%m-%d")
    existing = _csv_writers.get(sensor)

    if existing and existing[0] == today:
        return existing[1]

    if existing:
        existing[2].close()

    filepath = LOG_DIR / f"{sensor}_{today}.csv"
    is_new = not filepath.exists()
    fh = open(filepath, "a", newline="", encoding="utf-8")
    writer = csv.writer(fh)

    if is_new:
        writer.writerow(CSV_COLUMNS[sensor])
        log.info("Created log file: %s", filepath)

    _csv_writers[sensor] = (today, writer, fh)
    return writer


def log_reading(sensor: str, payload: dict, timestamp: str) -> None:
    """Append a sensor reading to today's CSV log."""
    try:
        writer = _get_csv_writer(sensor)
        row = [timestamp] + [payload.get(col) for col in CSV_COLUMNS[sensor][1:]]
        writer.writerow(row)
        _csv_writers[sensor][2].flush()
    except Exception as e:
        log.error("Failed to log %s reading: %s", sensor, e)

# ---------------------------------------------------------------------------
# Load history from today's log on startup
# ---------------------------------------------------------------------------

def _load_today_history() -> None:
    """Pre-fill the in-memory history buffer from today's CSV logs."""
    today = datetime.now().strftime("%Y-%m-%d")
    for sensor in ALL_KEYS:
        filepath = LOG_DIR / f"{sensor}_{today}.csv"
        if not filepath.exists():
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            for row in rows[-HISTORY_SIZE:]:
                payload = {}
                for col in CSV_COLUMNS[sensor][1:]:
                    val = row.get(col)
                    if val is None or val == "" or val == "None":
                        payload[col] = None
                    else:
                        try:
                            payload[col] = float(val)
                        except ValueError:
                            payload[col] = val
                history[sensor].append(payload)
            log.info("Loaded %d %s readings from today's log", len(history[sensor]), sensor)
        except Exception as e:
            log.error("Failed to load %s history: %s", sensor, e)

# ---------------------------------------------------------------------------
# MQTT subscriber (runs as background task)
# ---------------------------------------------------------------------------

async def mqtt_listener():
    global mqtt_connected, _mqtt_client
    while True:
        try:
            async with aiomqtt.Client(MQTT_BROKER, MQTT_PORT) as client:
                _mqtt_client = client
                mqtt_connected = True
                log.info("Connected to MQTT broker at %s:%s", MQTT_BROKER, MQTT_PORT)
                await client.subscribe("ems/#")
                async for msg in client.messages:
                    topic = str(msg.topic)
                    try:
                        payload = json.loads(msg.payload.decode())
                    except (json.JSONDecodeError, UnicodeDecodeError):
                        log.warning("Bad payload on %s", topic)
                        continue

                    now = datetime.now(timezone.utc).isoformat()

                    # ems/status/{lg} — ESP reports its own state
                    matched_sensor: str | None = None
                    matched_status = False
                    for lg, status_topic in STATUS_TOPICS.items():
                        if topic == status_topic:
                            control_state[lg].update(payload)
                            log.info("Status update from ESP for %s: %s", lg, payload)
                            matched_status = True
                            break

                    if not matched_status:
                        for sensor, sensor_topic in TOPICS.items():
                            if topic == sensor_topic:
                                latest[sensor] = payload
                                last_seen[sensor] = now
                                history[sensor].append(payload)
                                log_reading(sensor, payload, now)
                                matched_sensor = sensor
                                break
                        if matched_sensor is None:
                            log.debug("Unknown topic: %s", topic)

                    # Run IDS rules against every message (known or unknown topic)
                    sensor_history = list(history.get(matched_sensor or "", []))
                    triggered = ids_engine.evaluate_all(topic, payload, sensor_history)
                    for alert in triggered:
                        asyncio.create_task(_dispatch_alert(alert))

        except aiomqtt.MqttError as e:
            mqtt_connected = False
            log.warning("MQTT connection lost (%s), reconnecting in 2s …", e)
            await asyncio.sleep(2)
        except Exception as e:
            mqtt_connected = False
            log.error("MQTT listener error: %s", e)
            await asyncio.sleep(2)


@app.on_event("startup")
async def startup():
    _load_today_history()
    ids_engine.load_today_alerts()
    asyncio.create_task(mqtt_listener())
    log.info("MQTT listener started")


@app.on_event("shutdown")
async def shutdown():
    for sensor, (_, _, fh) in _csv_writers.items():
        try:
            fh.close()
        except Exception:
            pass
    log.info("CSV log files closed")

# ---------------------------------------------------------------------------
# REST endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    status = {
        "status": "ok",
        "mqtt_connected": mqtt_connected,
        "log_dir": str(LOG_DIR),
        "sensors": {},
    }
    for key in ALL_KEYS:
        status["sensors"][key] = {
            "last_seen": last_seen[key],
            "history_size": len(history[key]),
        }
    return status


@app.get("/alerts")
async def get_alerts():
    """Return all in-memory alerts (newest last)."""
    return [dataclasses.asdict(a) for a in ids_engine.alerts]


@app.websocket("/ws/alerts")
async def ws_alerts(ws: WebSocket):
    await ws.accept()
    q: asyncio.Queue = asyncio.Queue()
    _alert_queues.append(q)
    try:
        # Send existing alert history on connect
        for a in ids_engine.alerts:
            await ws.send_json(dataclasses.asdict(a))
        # Stream new alerts as they arrive
        while True:
            alert = await q.get()
            await ws.send_json(dataclasses.asdict(alert))
    except (WebSocketDisconnect, Exception):
        pass
    finally:
        if q in _alert_queues:
            _alert_queues.remove(q)


@app.get("/control/{load_group}")
async def get_control(load_group: str):
    if load_group not in LOAD_GROUPS:
        raise HTTPException(status_code=404, detail=f"Unknown load group: {load_group}")
    return control_state[load_group]


@app.post("/control/{load_group}")
async def send_control(load_group: str, request: Request):
    if load_group not in LOAD_GROUPS:
        raise HTTPException(status_code=404, detail=f"Unknown load group: {load_group}")
    if _mqtt_client is None:
        raise HTTPException(status_code=503, detail="MQTT broker not connected")

    body = await request.json()
    topic = f"ems/control/{load_group}"
    await _mqtt_client.publish(topic, json.dumps(body))

    # Update in-memory state
    control_state[load_group].update(body)
    log.info("Control command sent to %s: %s", topic, body)
    return {"ok": True, "state": control_state[load_group]}


@app.get("/logs")
async def list_logs():
    """List available log files with sizes."""
    files = []
    for f in sorted(LOG_DIR.glob("*.csv")):
        files.append({
            "name": f.name,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "modified": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return {"log_dir": str(LOG_DIR), "files": files}

# ---------------------------------------------------------------------------
# WebSocket endpoints — send history backlog, then stream live
# ---------------------------------------------------------------------------

async def _stream(ws: WebSocket, key: str, interval: float = 0.5):
    await ws.accept()
    try:
        for item in history[key]:
            await ws.send_json(item)

        last_sent = latest[key]
        while True:
            data = latest[key]
            if data is not None and data is not last_sent:
                await ws.send_json(data)
                last_sent = data
            await asyncio.sleep(interval)
    except (WebSocketDisconnect, Exception):
        pass


@app.websocket("/ws/battery")
async def ws_battery(ws: WebSocket):
    await _stream(ws, "battery")


@app.websocket("/ws/ac/load1")
async def ws_ac_load1(ws: WebSocket):
    await _stream(ws, "load1")


@app.websocket("/ws/ac/load2")
async def ws_ac_load2(ws: WebSocket):
    await _stream(ws, "load2")


@app.websocket("/ws/ac/load3")
async def ws_ac_load3(ws: WebSocket):
    await _stream(ws, "load3")
