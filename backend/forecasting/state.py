"""
Per-signal SARIMA state management.

At runtime the model is NEVER refitted — only .append(refit=False) is used.
Retraining is a separate offline step (train.py).
"""

from __future__ import annotations

import json
import logging
import pickle
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from .config import (
    ANOMALY_Z_THRESHOLD,
    MODELS_DIR,
    RESIDUAL_STATS_PATH,
    SIGNALS,
    SUSTAINED_ANOMALY_THRESHOLD,
)

log = logging.getLogger("forecasting.state")


@dataclass
class SignalState:
    model: Any                              # SARIMAXResults — replaced by .append() return
    res_mean: float
    res_std: float
    train_end_ts: pd.Timestamp
    next_pred: float | None = None          # prediction for the NEXT bucket (made this cycle)
    next_pred_ts: pd.Timestamp | None = None
    consecutive_anomalies: int = 0


def load_all() -> dict[str, SignalState]:
    """Load all trained models and their residual stats. Missing models are skipped."""
    if not RESIDUAL_STATS_PATH.exists():
        log.warning("residual_stats.json not found — run: python forecasting/train.py --all")
        return {}

    with open(RESIDUAL_STATS_PATH) as f:
        stats: dict = json.load(f)

    states: dict[str, SignalState] = {}
    for name in SIGNALS:
        model_path = MODELS_DIR / f"{name}.pkl"

        if not model_path.exists():
            log.warning("No model pickle for %s (%s) — skipping", name, model_path)
            continue
        if name not in stats:
            log.warning("No residual stats for %s — skipping", name)
            continue

        try:
            with open(model_path, "rb") as f:
                results = pickle.load(f)

            stat = stats[name]
            train_end_ts = pd.Timestamp(stat["train_end_ts"])
            if train_end_ts.tzinfo is None:
                train_end_ts = train_end_ts.tz_localize("UTC")

            states[name] = SignalState(
                model=results,
                res_mean=float(stat["mean"]),
                res_std=float(stat["std"]),
                train_end_ts=train_end_ts,
            )
            log.info("Loaded %s  (train_end=%s)", name, train_end_ts)
        except Exception as exc:
            log.error("Failed to load %s: %s", name, exc)

    return states


def process_bucket(
    state: SignalState,
    signal_name: str,
    ts: pd.Timestamp,
    actual: float,
) -> dict | None:
    """
    Process one 5s bucket.

    - If a prediction exists for this ts: compute residual + z-score.
      Normal  → append actual, reset anomaly counter.
      Anomaly → append predicted (imputation), increment counter, return record.
    - Always forecasts the next bucket and stores next_pred / next_pred_ts.
    - Returns an anomaly record dict or None.
    """
    anomaly_record: dict | None = None
    prev_pred = state.next_pred  # prediction for THIS bucket (made last cycle)

    if prev_pred is not None:
        residual = actual - prev_pred
        z_score = (
            (residual - state.res_mean) / state.res_std
            if state.res_std > 1e-9
            else 0.0
        )

        if abs(z_score) <= ANOMALY_Z_THRESHOLD:
            state.model = state.model.append([actual], refit=False)
            state.consecutive_anomalies = 0
        else:
            # Impute: feed model the predicted value so it doesn't learn attacker values
            state.model = state.model.append([prev_pred], refit=False)
            state.consecutive_anomalies += 1

            sustained = state.consecutive_anomalies >= SUSTAINED_ANOMALY_THRESHOLD
            abs_z = abs(z_score)
            if sustained or abs_z > 5:
                severity = "critical"
            elif abs_z > 3:
                severity = "high"
            else:
                severity = "medium"

            anomaly_record = {
                "timestamp": ts.isoformat(),
                "detection_type": "forecast_residual",
                "signal": signal_name,
                "predicted": round(prev_pred, 4),
                "actual": round(actual, 4),
                "residual": round(residual, 4),
                "residual_training_mean": round(state.res_mean, 4),
                "residual_training_std": round(state.res_std, 4),
                "z_score": round(z_score, 3),
                "severity": severity,
                "imputed": True,
                "consecutive_anomaly_count": state.consecutive_anomalies,
                "sustained": sustained,
            }
    else:
        # First bucket — no prior prediction, just seed the model state
        state.model = state.model.append([actual], refit=False)

    # Forecast the next bucket
    try:
        forecast = state.model.forecast(steps=1)
        state.next_pred = float(forecast.iloc[0])
        state.next_pred_ts = ts + pd.Timedelta(seconds=5)
    except Exception as exc:
        log.warning("Forecast failed for %s: %s", signal_name, exc)
        state.next_pred = None
        state.next_pred_ts = None

    return anomaly_record
