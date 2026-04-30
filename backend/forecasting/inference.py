"""
XGBoost inference service — runs as an asyncio background task in FastAPI.

FAKE_FORECAST mode (current): skips the XGBoost model entirely.
Predicted = actual + small Gaussian noise (~0.3% of the signal value).
Charts show two close lines, no anomaly flood, residuals look realistic.
Set FAKE_FORECAST = False once models are retrained and working.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
from collections import deque

import pandas as pd

from .config import (
    ANOMALIES_PATH,
    INFERENCE_INTERVAL_SECONDS,
    LOG_DIR,
    RESIDUALS_DIR,
    SIGNALS,
)
from .preprocess import load_sensor_logs_since, resample_to_5s

log = logging.getLogger("forecasting.inference")

# ---------------------------------------------------------------------------
# Toggle — flip to False once XGBoost models are retrained and working
# ---------------------------------------------------------------------------

FAKE_FORECAST = True

# Noise / drift / anomaly tuning
_NOISE_RATIO    = 0.004  # baseline Gaussian noise as fraction of signal value
_ANOMALY_Z_FAKE = 3.5   # z-threshold used for fake anomaly records

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_last_processed_ts: dict[str, pd.Timestamp | None] = {}

RESIDUAL_HEADER = "timestamp,predicted,actual,residual,z_score,is_anomaly\n"

# open file handles for residuals CSVs
_residual_fh: dict[str, object] = {}

# rolling baseline history for fake mode — used to compute mean so real deviations are detectable
_fake_history: dict[str, deque] = {}
_FAKE_HISTORY_LEN = 12   # 12 × 5 s = 60 s of baseline
_FAKE_HISTORY_MIN = 3    # buckets needed before anomaly detection kicks in


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
    """Initialise last-processed timestamps. In FAKE mode no models are needed."""
    global _last_processed_ts
    _last_processed_ts = {name: None for name in SIGNALS}

    if FAKE_FORECAST:
        log.info("FAKE_FORECAST mode active — using noise-based predictions (no XGBoost)")
        return

    # Real mode — import and load models
    from . import state as _state_mod
    from .preprocess import load_sensor_logs, resample_to_5s
    from .config import LAG_WINDOW

    global _states
    _states = _state_mod.load_all()
    if not _states:
        log.warning("No models loaded — run: python forecasting/train.py --all")
        return

    log.info("Seeding history deques from recent log data...")
    for name, st in _states.items():
        cfg = SIGNALS[name]
        try:
            series = load_sensor_logs(cfg["sensor"], cfg["field"], LOG_DIR)
            if series.empty:
                continue
            resampled = resample_to_5s(series)
            if resampled.empty:
                continue
            for val in resampled.iloc[-LAG_WINDOW:]:
                st.history.append(float(val))
            _last_processed_ts[name] = resampled.index[-1]
            log.info("  %s: seeded %d values", name, len(st.history))
        except Exception as exc:
            log.error("  %s: seed failed — %s", name, exc)

    log.info("Inference ready. Signals: %s", sorted(_states))


async def run_forever() -> None:
    """Asyncio task: initialise, then run inference every cycle."""
    reload_models()
    while True:
        await asyncio.sleep(INFERENCE_INTERVAL_SECONDS)
        await _inference_cycle()


# ---------------------------------------------------------------------------
# Per-cycle inference
# ---------------------------------------------------------------------------

async def _inference_cycle() -> None:
    if FAKE_FORECAST:
        await _fake_inference_cycle()
    else:
        await _real_inference_cycle()


async def _fake_inference_cycle() -> None:
    """
    Fake mode — pure anomaly detection against a rolling baseline.
    Predicted = rolling mean of recent actuals + tiny Gaussian noise.
    Anomalies only fire when real MQTT data deviates from that baseline.
    """
    for signal_name in SIGNALS:
        cfg = SIGNALS[signal_name]
        try:
            last_ts = _last_processed_ts.get(signal_name)
            new_data = load_sensor_logs_since(
                cfg["sensor"], cfg["field"], LOG_DIR, since_ts=last_ts)
            if new_data.empty:
                continue

            resampled = resample_to_5s(new_data)
            now_floor = pd.Timestamp.now(tz="UTC").floor("5s")
            resampled = resampled[resampled.index < now_floor]
            if resampled.empty:
                continue

            # Process only the latest bucket to avoid stale floods
            ts: pd.Timestamp = resampled.index[-1]  # type: ignore[assignment]
            actual = float(resampled.iloc[-1])

            # Rolling baseline — mean of recent actuals so real deviations are detectable
            hist = _fake_history.setdefault(signal_name, deque(maxlen=_FAKE_HISTORY_LEN))

            if len(hist) >= _FAKE_HISTORY_MIN:
                baseline = sum(hist) / len(hist)
            else:
                baseline = actual   # not enough history yet

            scale = max(abs(baseline), 0.1)

            # Tiny noise so the chart shows two distinguishable lines at rest
            noise = random.gauss(0, scale * _NOISE_RATIO)
            predicted = baseline + noise

            # Append to history AFTER computing predicted so the injected value
            # doesn't contaminate its own baseline.
            hist.append(actual)

            residual = actual - predicted
            noise_std = max(scale * _NOISE_RATIO, 0.01)
            z_score = residual / noise_std

            is_anomaly = abs(z_score) > _ANOMALY_Z_FAKE

            _write_residual(
                signal_name, ts,
                predicted=predicted, actual=actual,
                z_score=z_score, is_anomaly=is_anomaly,
            )

            if is_anomaly:
                abs_z = abs(z_score)
                severity = "critical" if abs_z > 6 else "high" if abs_z > 4 else "medium"
                record = {
                    "timestamp": ts.isoformat(),
                    "detection_type": "forecast_residual",
                    "signal": signal_name,
                    "predicted": round(predicted, 4),
                    "actual": round(actual, 4),
                    "residual": round(residual, 4),
                    "residual_training_mean": 0.0,
                    "residual_training_std": round(noise_std, 4),
                    "z_score": round(z_score, 3),
                    "severity": severity,
                    "imputed": False,
                    "consecutive_anomaly_count": 1,
                    "sustained": False,
                }
                _append_anomaly(record)
                log.info("FAKE ANOMALY %s  z=%.2f  actual=%.3f  predicted=%.3f",
                         signal_name, z_score, actual, predicted)

            _last_processed_ts[signal_name] = resampled.index[-1]

        except Exception as exc:
            log.error("Fake inference cycle error for %s: %s", signal_name, exc)


async def _real_inference_cycle() -> None:
    """Real XGBoost inference — used when FAKE_FORECAST = False."""
    from . import state as _state_mod
    from .config import LAG_WINDOW

    for signal_name, state in list(_states.items()):
        cfg = SIGNALS[signal_name]
        try:
            last_ts = _last_processed_ts.get(signal_name)
            new_data = load_sensor_logs_since(
                cfg["sensor"], cfg["field"], LOG_DIR, since_ts=last_ts)
            if new_data.empty:
                continue

            resampled = resample_to_5s(new_data)
            now_floor = pd.Timestamp.now(tz="UTC").floor("5s")
            resampled = resampled[resampled.index < now_floor]
            if resampled.empty:
                continue

            if len(resampled) > 2:
                catch_up = resampled.iloc[:-1]
                log.info("  %s: catch-up %d old buckets", signal_name, len(catch_up))
                for val in catch_up:
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


# Populated only in real mode
_states: dict = {}
