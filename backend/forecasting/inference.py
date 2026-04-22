"""
XGBoost inference service — runs as an asyncio background task in FastAPI.

Lifecycle:
  1. reload_models() called once at startup (and again on POST /api/forecasting/reload)
     - Loads pickles + residual stats via state.load_all()
     - Seeds each signal's history deque with the last LAG_WINDOW resampled values
       from today's CSV (instant — no backfill loop)
  2. run_forever() loops every INFERENCE_INTERVAL_SECONDS
     - Reads new telemetry rows written since last cycle
     - Resamples to 5s buckets, processes each in order
     - Anomalous buckets: imputed, logged to anomalies.jsonl
     - All processed buckets: written to residuals/{signal}.csv
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path

import pandas as pd

from .config import (
    ANOMALIES_PATH,
    INFERENCE_INTERVAL_SECONDS,
    LAG_WINDOW,
    LOG_DIR,
    RESIDUALS_DIR,
    SIGNALS,
)
from .preprocess import load_sensor_logs, load_sensor_logs_since, resample_to_5s
from . import state as _state_mod
from .state import SignalState

log = logging.getLogger("forecasting.inference")

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_states: dict[str, SignalState] = {}
_last_processed_ts: dict[str, pd.Timestamp | None] = {}
# open file handles for residuals CSVs
_residual_fh: dict[str, object] = {}

RESIDUAL_HEADER = "timestamp,predicted,actual,residual,z_score,is_anomaly\n"


# ---------------------------------------------------------------------------
# Residuals writer
# ---------------------------------------------------------------------------

def _residual_fh_for(signal_name: str):
    if signal_name in _residual_fh:
        return _residual_fh[signal_name]
    RESIDUALS_DIR.mkdir(parents=True, exist_ok=True)
    path = RESIDUALS_DIR / f"{signal_name}.csv"
    is_new = not path.exists()
    fh = open(path, "a", newline="", encoding="utf-8")
    if is_new:
        fh.write(RESIDUAL_HEADER)
    _residual_fh[signal_name] = fh
    return fh


def _write_residual(
    signal_name: str,
    ts: pd.Timestamp,
    predicted: float,
    actual: float,
    z_score: float,
    is_anomaly: bool,
) -> None:
    try:
        fh = _residual_fh_for(signal_name)
        residual = actual - predicted
        fh.write(
            f"{ts.isoformat()},{predicted:.4f},{actual:.4f},"
            f"{residual:.4f},{z_score:.3f},{int(is_anomaly)}\n"
        )
        fh.flush()
    except Exception as exc:
        log.error("residual write failed for %s: %s", signal_name, exc)


# ---------------------------------------------------------------------------
# Anomaly log
# ---------------------------------------------------------------------------

def _append_anomaly(record: dict) -> None:
    try:
        ANOMALIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(ANOMALIES_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as exc:
        log.error("anomaly write failed: %s", exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reload_models() -> None:
    """
    Load (or reload) all XGBoost models and seed each signal's history deque
    from the tail of the log CSVs. Safe to call multiple times.
    """
    global _states, _last_processed_ts

    log.info("Loading XGBoost models...")
    _states = _state_mod.load_all()
    _last_processed_ts = {name: None for name in _states}

    if not _states:
        log.warning("No models loaded — run: python forecasting/train.py --all")
        return

    log.info("Seeding history deques from recent log data...")
    for name, st in _states.items():
        cfg = SIGNALS[name]
        sensor = cfg["sensor"]
        field = cfg["field"]
        try:
            series = load_sensor_logs(sensor, field, LOG_DIR)
            if series.empty:
                log.info("  %s: no log data — will warm up from live data", name)
                continue

            resampled = resample_to_5s(series)
            if resampled.empty:
                log.info(
                    "  %s: resampled series empty — will warm up from live data", name)
                continue

            # Seed the deque with the last LAG_WINDOW values
            tail = resampled.iloc[-LAG_WINDOW:]
            for val in tail:
                st.history.append(float(val))

            # Anchor last_processed_ts so we don't re-read the whole CSV next cycle
            _last_processed_ts[name] = resampled.index[-1]
            log.info(
                "  %s: seeded %d/%d history values, last_ts=%s",
                name, len(st.history), LAG_WINDOW, _last_processed_ts[name],
            )
        except Exception as exc:
            log.error("  %s: seed failed — %s", name, exc)

    log.info("Inference ready. Signals: %s", sorted(_states))


async def run_forever() -> None:
    """Asyncio task: load models once, then process new buckets every cycle."""
    reload_models()
    while True:
        await asyncio.sleep(INFERENCE_INTERVAL_SECONDS)
        await _inference_cycle()


# ---------------------------------------------------------------------------
# Per-cycle inference
# ---------------------------------------------------------------------------

async def _inference_cycle() -> None:
    for signal_name, state in list(_states.items()):
        cfg = SIGNALS[signal_name]
        sensor = cfg["sensor"]
        field = cfg["field"]

        try:
            last_ts = _last_processed_ts.get(signal_name)
            new_data = load_sensor_logs_since(
                sensor, field, LOG_DIR, since_ts=last_ts)
            if new_data.empty:
                continue

            resampled = resample_to_5s(new_data)
            now_floor = pd.Timestamp.now(tz="UTC").floor("5s")
            resampled = resampled[resampled.index < now_floor]

            if resampled.empty:
                continue

            # If catching up on many buckets, silently seed history with all but
            # the last one, then only run full anomaly detection on the freshest bucket.
            if len(resampled) > 2:
                catch_up = resampled.iloc[:-1]
                log.info("  %s: catch-up %d old buckets (history seed only)",
                         signal_name, len(catch_up))
                for val in catch_up:
                    # Just push into history — don't run anomaly detection on stale data
                    if len(state.history) >= LAG_WINDOW:
                        state.history.append(float(val))
                    else:
                        state.history.append(float(val))
                resampled = resampled.iloc[-1:]

            for i in range(len(resampled)):
                ts: pd.Timestamp = resampled.index[i]  # type: ignore[assignment]
                actual = float(resampled.iloc[i])
                predicted, record = _state_mod.process_bucket(
                    state, signal_name, ts, actual)

                if predicted is not None:
                    z_score = record["z_score"] if record else 0.0
                    _write_residual(
                        signal_name, ts,
                        predicted=predicted, actual=actual,
                        z_score=z_score, is_anomaly=record is not None,
                    )

                if record:
                    _append_anomaly(record)
                    log.warning(
                        "ANOMALY %s  z=%.2f  actual=%.3f  predicted=%.3f  "
                        "consecutive=%d  sustained=%s",
                        signal_name, record["z_score"], actual, record["predicted"],
                        record["consecutive_anomaly_count"], record["sustained"],
                    )

            _last_processed_ts[signal_name] = resampled.index[-1]

        except Exception as exc:
            log.error("Inference cycle error for %s: %s", signal_name, exc)
