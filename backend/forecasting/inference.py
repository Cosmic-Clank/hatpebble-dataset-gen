"""
SARIMA inference service — runs as an asyncio background task in FastAPI.

Lifecycle:
  1. reload_models() called once at startup (and again on POST /api/forecasting/reload)
     - Loads pickles via state.load_all()
     - Silently backfills model state from train_end → now (no anomaly detection)
     - Primes each model's first forecast
  2. run_forever() loops every INFERENCE_INTERVAL_SECONDS
     - Reads new telemetry rows from today's CSV
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
_residual_fh: dict[str, object] = {}          # open file handles for residuals CSVs

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
# Cold-start backfill
# ---------------------------------------------------------------------------

def _backfill(state: SignalState, signal_name: str, cfg: dict) -> None:
    """
    Silently append buckets from train_end_ts to now.
    No anomaly detection, no residual writes — just updates the model's internal state.
    After backfill, primes the first live forecast.
    """
    sensor = cfg["sensor"]
    field = cfg["field"]

    try:
        series = load_sensor_logs(sensor, field, LOG_DIR)
        if series.empty:
            log.info("  %s: no log data yet for backfill", signal_name)
            return

        new = series[series.index > state.train_end_ts]
        if new.empty:
            log.info("  %s: no data after train_end — no backfill needed", signal_name)
        else:
            resampled = resample_to_5s(new)
            now_floor = pd.Timestamp.now(tz="UTC").floor("5s")
            resampled = resampled[resampled.index < now_floor]

            if not resampled.empty:
                log.info(
                    "  %s: backfilling %d buckets (%s → %s)",
                    signal_name, len(resampled),
                    resampled.index[0], resampled.index[-1],
                )
                for val in resampled.values:
                    state.model = state.model.append([float(val)], refit=False)
                _last_processed_ts[signal_name] = resampled.index[-1]
            else:
                log.info("  %s: backfill range is empty", signal_name)

        # Prime first forecast regardless
        forecast = state.model.forecast(steps=1)
        state.next_pred = float(forecast.iloc[0])
        state.next_pred_ts = (
            (_last_processed_ts.get(signal_name) or state.train_end_ts)
            + pd.Timedelta(seconds=5)
        )
        log.info("  %s: first forecast → %.4f for %s", signal_name, state.next_pred, state.next_pred_ts)

    except Exception as exc:
        log.error("Backfill failed for %s: %s", signal_name, exc)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def reload_models() -> None:
    """Load (or reload) all SARIMA models and run backfill. Safe to call multiple times."""
    global _states, _last_processed_ts

    log.info("Loading SARIMA models...")
    _states = _state_mod.load_all()
    _last_processed_ts = {name: None for name in _states}

    if not _states:
        log.warning("No models loaded — run: python forecasting/train.py --all")
        return

    log.info("Running cold-start backfill for %d signals...", len(_states))
    for name, st in _states.items():
        _backfill(st, name, SIGNALS[name])

    log.info("Inference ready. Signals: %s", sorted(_states))


async def run_forever() -> None:
    """Asyncio task: load models once, then process one bucket per cycle."""
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
            new_data = load_sensor_logs_since(sensor, field, LOG_DIR, since_ts=last_ts)
            if new_data.empty:
                continue

            resampled = resample_to_5s(new_data)
            now_floor = pd.Timestamp.now(tz="UTC").floor("5s")
            resampled = resampled[resampled.index < now_floor]

            if resampled.empty:
                continue

            for ts, actual_val in resampled.items():
                actual = float(actual_val)
                prev_pred = state.next_pred  # prediction for THIS bucket

                record = _state_mod.process_bucket(state, signal_name, ts, actual)

                # Write residual (only when we had a prior prediction)
                if prev_pred is not None:
                    z_score = record["z_score"] if record else 0.0
                    _write_residual(
                        signal_name, ts,
                        predicted=prev_pred, actual=actual,
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
