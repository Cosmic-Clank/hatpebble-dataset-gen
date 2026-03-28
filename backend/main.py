from __future__ import annotations

import asyncio
import csv
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import aiomqtt
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("ems")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MQTT_BROKER = "localhost"
MQTT_PORT = 1883
TOPICS = {"battery": "ems/battery", "ac": "ems/ac"}

# In-memory history buffer size (sent to new WebSocket clients on connect)
HISTORY_SIZE = 120

# Log directory — one CSV per sensor per day
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# CSV column order (must match the JSON keys from ESP32 / mock publisher)
CSV_COLUMNS = {
    "battery": [
        "timestamp", "time", "battery_voltage", "battery_current",
        "battery_power", "soc", "consumed_ah", "time_to_go",
        "alarm_flags", "temperature",
    ],
    "ac": [
        "timestamp", "date", "time", "ac_voltage", "ac_current",
        "active_power", "active_energy", "frequency", "power_factor",
    ],
}

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

# Shared state
latest: dict[str, dict | None] = {"battery": None, "ac": None}
last_seen: dict[str, str | None] = {"battery": None, "ac": None}
history: dict[str, deque[dict]] = {
    "battery": deque(maxlen=HISTORY_SIZE),
    "ac": deque(maxlen=HISTORY_SIZE),
}
mqtt_connected = False

# Track open CSV file handles so we rotate daily
_csv_writers: dict[str, tuple[str, csv.writer, object]] = {}  # key -> (date_str, writer, file_handle)

# ---------------------------------------------------------------------------
# CSV data logger
# ---------------------------------------------------------------------------

def _get_csv_writer(sensor: str) -> csv.writer:
    """Return a CSV writer for today's log file, rotating daily."""
    today = datetime.now().strftime("%Y-%m-%d")
    existing = _csv_writers.get(sensor)

    # If we already have a writer for today, reuse it
    if existing and existing[0] == today:
        return existing[1]

    # Close previous day's file if open
    if existing:
        existing[2].close()

    # Create new file for today
    filepath = LOG_DIR / f"{sensor}_{today}.csv"
    is_new = not filepath.exists()
    fh = open(filepath, "a", newline="", encoding="utf-8")
    writer = csv.writer(fh)

    # Write header if new file
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
        # Flush after every write so data isn't lost on crash
        _csv_writers[sensor][2].flush()
    except Exception as e:
        log.error("Failed to log %s reading: %s", sensor, e)

# ---------------------------------------------------------------------------
# Load history from today's log on startup
# ---------------------------------------------------------------------------

def _load_today_history() -> None:
    """Pre-fill the in-memory history buffer from today's CSV logs."""
    today = datetime.now().strftime("%Y-%m-%d")
    for sensor in ("battery", "ac"):
        filepath = LOG_DIR / f"{sensor}_{today}.csv"
        if not filepath.exists():
            continue
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                rows = list(reader)
            # Take the last HISTORY_SIZE rows
            for row in rows[-HISTORY_SIZE:]:
                # Reconstruct the JSON payload (exclude the timestamp column)
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
    global mqtt_connected
    while True:
        try:
            async with aiomqtt.Client(MQTT_BROKER, MQTT_PORT) as client:
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

                    for sensor, sensor_topic in TOPICS.items():
                        if topic == sensor_topic:
                            latest[sensor] = payload
                            last_seen[sensor] = now
                            history[sensor].append(payload)
                            log_reading(sensor, payload, now)
                            break
                    else:
                        log.debug("Unknown topic: %s", topic)

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
    asyncio.create_task(mqtt_listener())
    log.info("MQTT listener started")


@app.on_event("shutdown")
async def shutdown():
    # Close any open CSV file handles
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
    return {
        "status": "ok",
        "mqtt_connected": mqtt_connected,
        "battery_last_seen": last_seen["battery"],
        "ac_last_seen": last_seen["ac"],
        "battery_history_size": len(history["battery"]),
        "ac_history_size": len(history["ac"]),
        "log_dir": str(LOG_DIR),
    }


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
        # Send full history backlog so charts are pre-filled
        for item in history[key]:
            await ws.send_json(item)

        # Then stream live updates
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


@app.websocket("/ws/ac")
async def ws_ac(ws: WebSocket):
    await _stream(ws, "ac")
