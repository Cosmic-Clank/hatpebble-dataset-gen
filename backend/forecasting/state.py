"""
Per-signal XGBoost state management.

Each signal carries:
  - a trained XGBRegressor (loaded once, never retrained at runtime)
  - residual mean + std from training (used for z-score computation)
  - a rolling history deque of the last LAG_WINDOW values

process_bucket() is stateless from the model's perspective: it builds a
feature vector from the deque, calls model.predict(), and updates the deque.
"""

from __future__ import annotations

import json
import logging
import pickle
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from .config import (
    ANOMALY_Z_THRESHOLD,
    LAG_WINDOW,
    MODELS_DIR,
    RESIDUAL_STATS_PATH,
    SIGNALS,
    SUSTAINED_ANOMALY_THRESHOLD,
)

log = logging.getLogger("forecasting.state")


@dataclass
class SignalState:
    model: Any                                        # XGBRegressor
    res_mean: float
    res_std: float
    history: deque = field(default_factory=lambda: deque(maxlen=LAG_WINDOW))
    consecutive_anomalies: int = 0


def load_all() -> dict[str, SignalState]:
    """Load all trained XGBoost models and residual stats. Missing models are skipped."""
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
                model = pickle.load(f)

            stat = stats[name]
            states[name] = SignalState(
                model=model,
                res_mean=float(stat["mean"]),
                res_std=float(stat["std"]),
                history=deque(maxlen=LAG_WINDOW),
            )
            log.info("Loaded %s  (res_std=%.4f)", name, float(stat["std"]))
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

    Warming up (history not full yet):
        Append actual to history, return None.

    Ready:
        Build feature vector → predict → compute residual + z-score.
        Normal  → append actual, reset anomaly counter, return None.
        Anomaly → append predicted (imputation), increment counter, return record.
    """
    # Warming up — not enough history to predict yet
    if len(state.history) < LAG_WINDOW:
        state.history.append(actual)
        return None

    # Build feature vector: [v(t-1), v(t-2), ..., v(t-LAG), hour, minute]
    lags = list(reversed(state.history))           # most-recent first
    features = np.array([[*lags, ts.hour, ts.minute]], dtype=np.float32)
    predicted = float(state.model.predict(features)[0])

    residual = actual - predicted
    z_score = (
        (residual - state.res_mean) / state.res_std
        if state.res_std > 1e-9
        else 0.0
    )

    if abs(z_score) <= ANOMALY_Z_THRESHOLD:
        state.history.append(actual)
        state.consecutive_anomalies = 0
        return None

    # Anomaly — impute with predicted so the history stays clean
    state.history.append(predicted)
    state.consecutive_anomalies += 1

    sustained = state.consecutive_anomalies >= SUSTAINED_ANOMALY_THRESHOLD
    abs_z = abs(z_score)
    if sustained or abs_z > 5:
        severity = "critical"
    elif abs_z > 3:
        severity = "high"
    else:
        severity = "medium"

    return {
        "timestamp": ts.isoformat(),
        "detection_type": "forecast_residual",
        "signal": signal_name,
        "predicted": round(predicted, 4),
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
