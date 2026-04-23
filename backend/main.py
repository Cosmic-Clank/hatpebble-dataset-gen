from __future__ import annotations
from forecasting.config import ANOMALIES_PATH, RESIDUALS_DIR, SIGNALS

import asyncio
import csv
import json
import logging
import os
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
import dataclasses
from typing import Optional

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent / ".env")

import openai
import pandas as pd
import aiomqtt
import ids as ids_engine
import forecasting.inference as _forecasting
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

_openai_client = openai.AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

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
history: dict[str, deque[dict]] = {
    k: deque(maxlen=HISTORY_SIZE) for k in ALL_KEYS}
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
        row = [timestamp] + [payload.get(col)
                             for col in CSV_COLUMNS[sensor][1:]]
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
            log.info("Loaded %d %s readings from today's log",
                     len(history[sensor]), sensor)
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
                log.info("Connected to MQTT broker at %s:%s",
                         MQTT_BROKER, MQTT_PORT)
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
                            log.info(
                                "Status update from ESP for %s: %s", lg, payload)
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
                    sensor_history = list(
                        history.get(matched_sensor or "", []))
                    triggered = ids_engine.evaluate_all(
                        topic, payload, sensor_history)
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
    print("ITS HERE")
    asyncio.create_task(_forecasting.run_forever())
    log.info("MQTT listener started")


@app.on_event("shutdown")
async def shutdown():
    for sensor, (_, _, fh) in _csv_writers.items():
        try:
            fh.close()
        except Exception:
            pass
    log.info("CSV log files closed")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)

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
        raise HTTPException(
            status_code=404, detail=f"Unknown load group: {load_group}")
    return control_state[load_group]


@app.post("/control/{load_group}")
async def send_control(load_group: str, request: Request):
    if load_group not in LOAD_GROUPS:
        raise HTTPException(
            status_code=404, detail=f"Unknown load group: {load_group}")
    if _mqtt_client is None:
        raise HTTPException(
            status_code=503, detail="MQTT broker not connected")

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


def _parse_ts(ts_str: str | None, default: datetime) -> datetime:
    if not ts_str:
        return default
    ts_str = ts_str.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(ts_str)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid timestamp: {ts_str!r}")


def _clean_records(df: pd.DataFrame) -> list[dict]:
    """Convert DataFrame to JSON-safe list of dicts (NaN → None)."""
    records = df.to_dict(orient="records")
    out = []
    for row in records:
        out.append({k: (None if (isinstance(v, float) and v != v) else v)
                    for k, v in row.items()})
    return out


def _load_csvs_for_range(pattern: str, dt_from: datetime, dt_to: datetime,
                          date_prefix_len: int = 1) -> pd.DataFrame:
    """
    Load all CSV files matching `pattern` whose embedded date overlaps [dt_from, dt_to].
    `date_prefix_len` = number of underscore-separated prefix tokens before the date.
    e.g. "battery_2026-04-23.csv" → prefix_len=1, "alerts_2026-04-23.csv" → prefix_len=1
    """
    dfs = []
    for f in sorted(LOG_DIR.glob(pattern)):
        parts = f.stem.split("_", date_prefix_len)
        if len(parts) < date_prefix_len + 1:
            continue
        date_str = parts[date_prefix_len]
        try:
            file_date = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if file_date.date() < (dt_from - timedelta(days=1)).date():
            continue
        if file_date.date() > (dt_to + timedelta(days=1)).date():
            continue
        try:
            dfs.append(pd.read_csv(f, dtype=str))
        except Exception as exc:
            log.error("Failed to read %s: %s", f, exc)
    if not dfs:
        return pd.DataFrame()
    return pd.concat(dfs, ignore_index=True)


@app.get("/api/logs/sensor")
async def get_sensor_logs(
    sensor: str = Query(..., description="battery | load1 | load2 | load3"),
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    limit: int = Query(2000, ge=1, le=20000),
):
    """Return historical sensor readings from daily CSV logs."""
    if sensor not in ALL_KEYS:
        raise HTTPException(status_code=400, detail=f"Unknown sensor: {sensor}. Valid: {ALL_KEYS}")

    now = datetime.now(timezone.utc)
    dt_from = _parse_ts(from_ts, now - timedelta(hours=24))
    dt_to   = _parse_ts(to_ts, now)

    df = _load_csvs_for_range(f"{sensor}_*.csv", dt_from, dt_to, date_prefix_len=1)
    if df.empty:
        return []

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df[(df["timestamp"] >= dt_from) & (df["timestamp"] <= dt_to)]

    # Convert numeric columns
    for col in df.columns:
        if col not in ("timestamp", "date", "time", "alarm_flags"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("timestamp").tail(limit)
    df["timestamp"] = df["timestamp"].apply(lambda t: t.isoformat())
    return _clean_records(df)


@app.get("/api/logs/alerts")
async def get_alerts_log(
    from_ts: Optional[str] = Query(None, alias="from"),
    to_ts: Optional[str] = Query(None, alias="to"),
    severity: Optional[str] = Query(None, description="info | warning | critical"),
    limit: int = Query(2000, ge=1, le=20000),
):
    """Return historical IDS alerts from daily alert CSV logs."""
    now = datetime.now(timezone.utc)
    dt_from = _parse_ts(from_ts, now - timedelta(hours=24))
    dt_to   = _parse_ts(to_ts, now)

    df = _load_csvs_for_range("alerts_*.csv", dt_from, dt_to, date_prefix_len=1)
    if df.empty:
        return []

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df[(df["timestamp"] >= dt_from) & (df["timestamp"] <= dt_to)]

    if severity:
        df = df[df["severity"] == severity]

    df = df.sort_values("timestamp").tail(limit)
    df["timestamp"] = df["timestamp"].apply(lambda t: t.isoformat())
    return _clean_records(df)

# ---------------------------------------------------------------------------
# Forecasting / anomaly detection endpoints
# ---------------------------------------------------------------------------


@app.get("/api/anomalies")
async def get_anomalies(
    limit: int = Query(100, ge=1, le=5000),
    signal: Optional[str] = Query(None),
    since: Optional[str] = Query(None),
    to: Optional[str] = Query(None),
):
    """Return anomaly records from anomalies.jsonl (newest first)."""
    if not ANOMALIES_PATH.exists():
        return []
    records: list[dict] = []
    with open(ANOMALIES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    if signal:
        records = [r for r in records if r.get("signal") == signal]
    if since:
        records = [r for r in records if r.get("timestamp", "") >= since]
    if to:
        records = [r for r in records if r.get("timestamp", "") <= to]
    return list(reversed(records))[-limit:]


@app.get("/api/anomalies/summary")
async def get_anomalies_summary():
    """Count anomalies by severity and signal for the last 24h."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    counts: dict = {"critical": 0, "high": 0, "medium": 0, "by_signal": {}}
    if ANOMALIES_PATH.exists():
        with open(ANOMALIES_PATH, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if r.get("timestamp", "") < cutoff:
                        continue
                    sev = r.get("severity", "medium")
                    counts[sev] = counts.get(sev, 0) + 1
                    sig = r.get("signal", "unknown")
                    counts["by_signal"][sig] = counts["by_signal"].get(
                        sig, 0) + 1
                except json.JSONDecodeError:
                    pass
    return counts


@app.get("/api/residuals/{signal}")
async def get_residuals(signal: str, window: int = Query(300, ge=10, le=86400)):
    """Return predicted vs actual residual data for the last `window` seconds."""
    if signal not in SIGNALS:
        raise HTTPException(
            status_code=404, detail=f"Unknown signal: {signal}")
    path = RESIDUALS_DIR / f"{signal}.csv"
    if not path.exists():
        return []
    cutoff = (datetime.now(timezone.utc) -
              timedelta(seconds=window)).isoformat()
    rows: list[dict] = []
    with open(path, "r", encoding="utf-8") as f:
        import csv as _csv
        reader = _csv.DictReader(f)
        for row in reader:
            if row.get("timestamp", "") >= cutoff:
                rows.append({
                    "timestamp": row["timestamp"],
                    "predicted": float(row["predicted"]) if row.get("predicted") else None,
                    "actual": float(row["actual"]) if row.get("actual") else None,
                    "residual": float(row["residual"]) if row.get("residual") else None,
                    "z_score": float(row["z_score"]) if row.get("z_score") else None,
                    "is_anomaly": row.get("is_anomaly") == "1",
                })
    return rows


@app.post("/api/forecasting/reload")
async def reload_forecasting():
    """Reload SARIMA models from disk and rerun backfill. Elevated access only."""
    _forecasting.reload_models()
    return {"ok": True, "loaded": list(_forecasting._states.keys())}


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


# ---------------------------------------------------------------------------
# AI Insights — natural language query endpoint
# ---------------------------------------------------------------------------

_BATTERY_VALUE_COLS = ["battery_voltage", "battery_current", "battery_power", "soc", "temperature"]
_LOAD_VALUE_COLS    = ["ac_voltage", "ac_current", "active_power", "active_energy", "frequency", "power_factor"]


def _aggregate_df(df: pd.DataFrame, time_col: str, value_cols: list[str],
                  dt_from: datetime, dt_to: datetime) -> list[dict]:
    """Bucket a sensor DataFrame by adaptive time resolution."""
    span_hours = (dt_to - dt_from).total_seconds() / 3600
    if span_hours <= 6:
        freq = "5min"
    elif span_hours <= 48:
        freq = "1h"
    elif span_hours <= 336:
        freq = "1D"
    else:
        freq = "1W"

    df = df.copy()
    df[time_col] = pd.to_datetime(df[time_col], utc=True, errors="coerce")
    df = df.dropna(subset=[time_col])
    df = df[(df[time_col] >= dt_from) & (df[time_col] <= dt_to)]
    if df.empty:
        return []

    for col in value_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.set_index(time_col).sort_index()
    rows: list[dict] = []
    for bucket_ts, group in df[value_cols].resample(freq):
        if group.empty:
            continue
        row: dict = {"bucket_start": bucket_ts.isoformat(), "count": int(len(group))}
        for col in value_cols:
            vals = group[col].dropna()
            if vals.empty:
                row[f"{col}_min"] = row[f"{col}_max"] = row[f"{col}_avg"] = None
            else:
                row[f"{col}_min"] = round(float(vals.min()), 4)
                row[f"{col}_max"] = round(float(vals.max()), 4)
                row[f"{col}_avg"] = round(float(vals.mean()), 4)
        rows.append(row)
    return rows[:500]


def _execute_query_sensor_data(sensor: str, from_iso: str, to_iso: str,
                                fields: list[str] | None) -> dict:
    now = datetime.now(timezone.utc)
    dt_from = _parse_ts(from_iso, now - timedelta(days=1))
    dt_to   = _parse_ts(to_iso, now)

    df = _load_csvs_for_range(f"{sensor}_*.csv", dt_from, dt_to, date_prefix_len=1)
    if df.empty:
        return {"error": f"No data found for sensor '{sensor}' in the requested range.", "buckets": []}

    all_cols = _BATTERY_VALUE_COLS if sensor == "battery" else _LOAD_VALUE_COLS
    value_cols = [f for f in (fields or all_cols) if f in all_cols]
    if not value_cols:
        return {"error": f"None of the requested fields are valid for sensor '{sensor}'.", "buckets": []}

    buckets = _aggregate_df(df, "timestamp", value_cols, dt_from, dt_to)
    return {
        "sensor": sensor,
        "from": from_iso,
        "to": to_iso,
        "bucket_count": len(buckets),
        "fields_aggregated": value_cols,
        "buckets": buckets,
    }


def _execute_query_alert_data(from_iso: str, to_iso: str, severity: str | None) -> dict:
    now = datetime.now(timezone.utc)
    dt_from = _parse_ts(from_iso, now - timedelta(days=1))
    dt_to   = _parse_ts(to_iso, now)

    df = _load_csvs_for_range("alerts_*.csv", dt_from, dt_to, date_prefix_len=1)
    if df.empty:
        return {"total": 0, "by_severity": {}, "sample_alerts": []}

    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df[(df["timestamp"] >= dt_from) & (df["timestamp"] <= dt_to)]

    sev_filter = severity if severity and severity != "all" else None
    if sev_filter:
        df = df[df["severity"] == sev_filter]

    by_severity = df["severity"].value_counts().to_dict() if "severity" in df.columns else {}
    sample = df.sort_values("timestamp", ascending=False).head(20).copy()
    sample["timestamp"] = sample["timestamp"].apply(lambda t: t.isoformat())
    cols = [c for c in ["timestamp", "rule", "severity", "message"] if c in sample.columns]
    return {
        "total": int(len(df)),
        "by_severity": {str(k): int(v) for k, v in by_severity.items()},
        "sample_alerts": _clean_records(sample[cols].fillna("")),
    }


def _execute_query_anomaly_data(from_iso: str, to_iso: str, signal: str | None) -> dict:
    if not ANOMALIES_PATH.exists():
        return {"total": 0, "by_severity": {}, "by_signal": {}, "top_anomalies": []}

    records: list[dict] = []
    with open(ANOMALIES_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    records = [r for r in records if from_iso <= r.get("timestamp", "") <= to_iso]
    if signal:
        records = [r for r in records if r.get("signal") == signal]

    by_severity: dict[str, int] = {}
    by_signal: dict[str, int] = {}
    for r in records:
        sev = r.get("severity", "medium")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        sig = r.get("signal", "unknown")
        by_signal[sig] = by_signal.get(sig, 0) + 1

    top = sorted(records, key=lambda r: abs(r.get("z_score", 0)), reverse=True)[:20]
    return {
        "total": len(records),
        "by_severity": by_severity,
        "by_signal": by_signal,
        "top_anomalies": [
            {
                "timestamp": r.get("timestamp"),
                "signal":    r.get("signal"),
                "z_score":   round(r.get("z_score", 0), 3),
                "severity":  r.get("severity"),
                "sustained": r.get("sustained", False),
            }
            for r in top
        ],
    }


def _dispatch_ai_tool(name: str, arguments: dict) -> str:
    try:
        if name == "query_sensor_data":
            result = _execute_query_sensor_data(
                sensor=arguments["sensor"],
                from_iso=arguments["from_iso"],
                to_iso=arguments["to_iso"],
                fields=arguments.get("fields"),
            )
        elif name == "query_alert_data":
            result = _execute_query_alert_data(
                from_iso=arguments["from_iso"],
                to_iso=arguments["to_iso"],
                severity=arguments.get("severity"),
            )
        elif name == "query_anomaly_data":
            result = _execute_query_anomaly_data(
                from_iso=arguments["from_iso"],
                to_iso=arguments["to_iso"],
                signal=arguments.get("signal"),
            )
        else:
            result = {"error": f"Unknown tool: {name}"}
    except Exception as exc:
        result = {"error": str(exc)}
    return json.dumps(result)


_AI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_sensor_data",
            "description": (
                "Fetch aggregated sensor readings from daily CSV logs. "
                "Returns time-bucketed min/max/avg/count for the requested columns. "
                "Battery sensor columns: battery_voltage, battery_current, battery_power, soc, temperature. "
                "Load sensors (load1/load2/load3) columns: ac_voltage, ac_current, active_power, active_energy, frequency, power_factor."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "sensor": {
                        "type": "string",
                        "enum": ["battery", "load1", "load2", "load3"],
                    },
                    "from_iso": {"type": "string", "description": "Start of time range in ISO 8601 UTC, e.g. 2026-04-20T00:00:00Z"},
                    "to_iso":   {"type": "string", "description": "End of time range in ISO 8601 UTC."},
                    "fields": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific column names to aggregate. Omit for all available fields.",
                    },
                },
                "required": ["sensor", "from_iso", "to_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_alert_data",
            "description": (
                "Fetch IDS security alert records from daily alert CSV logs. "
                "Returns total count, breakdown by severity, and a sample of recent alerts. "
                "Severity values: info, warning, critical."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_iso": {"type": "string"},
                    "to_iso":   {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["info", "warning", "critical", "all"],
                        "description": "Filter by severity. Use 'all' for no filter.",
                    },
                },
                "required": ["from_iso", "to_iso"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_anomaly_data",
            "description": (
                "Fetch SARIMA anomaly detections from the anomalies log. "
                "Returns total count, breakdown by severity and signal, and top anomalies by z-score magnitude. "
                "Each anomaly has: timestamp, signal, z_score, severity (medium/high/critical), sustained (bool)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "from_iso": {"type": "string"},
                    "to_iso":   {"type": "string"},
                    "signal": {
                        "type": "string",
                        "description": "Optional signal name filter, e.g. 'load1_active_power'. Omit for all signals.",
                    },
                },
                "required": ["from_iso", "to_iso"],
            },
        },
    },
]

_AI_SYSTEM_PROMPT = """\
You are an AI assistant embedded in a Smart Grid Energy Management System (EMS) dashboard.

You have access to three data tools:
- query_sensor_data: Reads battery or AC load sensor readings from CSV logs. Returns time-bucketed statistics (min/max/avg) per bucket. Battery columns: battery_voltage (V), battery_current (A), battery_power (W), soc (%), temperature (°C). Load groups (load1/load2/load3) columns: ac_voltage, ac_current, active_power (W), active_energy (kWh), frequency (Hz), power_factor.
- query_alert_data: Reads IDS security alerts (info/warning/critical) from the intrusion detection system.
- query_anomaly_data: Reads SARIMA-based anomaly detections with z-scores per signal.

Rules:
- Always call the appropriate tool(s) before answering. Do not guess from memory.
- Today's UTC date is {today_utc}. Use this as the reference point for all relative time expressions ("last 3 days", "this week", "today").
- For "this week" use Monday 00:00:00Z as from_iso. For "last N days" compute from_iso as today minus N days.
- Return concise factual answers with specific numbers. Round values to 2 decimal places.
- If data is empty or unavailable, say so clearly.
- Do not mention internal tool names, JSON, or bucket structure in your answer. Speak naturally.
"""


class AIQueryRequest(BaseModel):
    question: str


@app.post("/api/ai/query")
async def ai_query(body: AIQueryRequest):
    """Answer a natural language question about EMS sensor/alert/anomaly data."""
    if not body.question.strip():
        raise HTTPException(status_code=400, detail="Question must not be empty.")

    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise HTTPException(status_code=503, detail="OpenAI API key not configured on the server.")

    today_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    system_content = _AI_SYSTEM_PROMPT.replace("{today_utc}", today_utc)

    messages: list[dict] = [
        {"role": "system", "content": system_content},
        {"role": "user",   "content": body.question.strip()},
    ]
    tools_used: list[str] = []

    loop = asyncio.get_event_loop()

    for _ in range(3):
        response = await _openai_client.chat.completions.create(
            model="gpt-4o-mini",
            messages=messages,
            tools=_AI_TOOLS,
            tool_choice="auto",
            temperature=0.2,
            max_tokens=1024,
        )
        msg = response.choices[0].message

        if not msg.tool_calls:
            return {"answer": msg.content or "No answer generated.", "tools_used": tools_used}

        messages.append(msg)
        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                arguments = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                arguments = {}
            tools_used.append(tool_name)
            result_json = await loop.run_in_executor(None, _dispatch_ai_tool, tool_name, arguments)
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_json,
            })

    raise HTTPException(status_code=500, detail="AI query did not converge to a final answer.")
