"""
XGBoost training script — run once to produce model pickles.

For each signal, reads the live telemetry CSVs, resamples to 5s buckets,
builds a lag feature matrix, fits an XGBRegressor, and saves the model
along with residual statistics used for z-score anomaly detection.

Usage (from backend/):
    python forecasting/train.py --all
    python forecasting/train.py --signal load1_ac_voltage
"""

from __future__ import annotations

import argparse
import json
import logging
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from forecasting.config import (
    ANOMALY_Z_THRESHOLD,
    LAG_WINDOW,
    LOG_DIR,
    MIN_TRAINING_BUCKETS,
    MODELS_DIR,
    RESIDUAL_STATS_PATH,
    SIGNALS,
    XGB_LEARNING_RATE,
    XGB_MAX_DEPTH,
    XGB_N_ESTIMATORS,
)
from forecasting.preprocess import load_sensor_logs, resample_to_5s

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("train")


def build_features(series: pd.Series, lag: int) -> tuple[np.ndarray, np.ndarray]:
    """
    Build (X, y) arrays from a time series using lag features + time-of-day.

    Each row of X: [v(t-1), v(t-2), ..., v(t-lag), hour, minute]
    y[i]:          v(t)
    """
    vals = series.values
    idx = series.index
    X, y = [], []
    for i in range(lag, len(vals)):
        lags = vals[i - lag:i][::-1]   # [t-1, t-2, ..., t-lag]
        ts = idx[i]
        X.append([*lags, ts.hour, ts.minute])
        y.append(vals[i])
    return np.array(X, dtype=np.float32), np.array(y, dtype=np.float32)


def train_signal(signal_name: str, cfg: dict) -> dict | None:
    sensor = cfg["sensor"]
    field = cfg["field"]

    log.info("── %s  (%s.%s)", signal_name, sensor, field)
    series = load_sensor_logs(sensor, field, LOG_DIR)

    if series.empty:
        log.warning("  No data — run mock_training_data.py first, then retry.")
        return None

    resampled = resample_to_5s(series)
    n = len(resampled)

    if n < MIN_TRAINING_BUCKETS:
        log.warning(
            "  Only %d resampled buckets (need %d). "
            "Run: python mock_training_data.py --seconds 3600",
            n, MIN_TRAINING_BUCKETS,
        )
        return None

    log.info("  %d buckets  %s → %s", n, resampled.index[0], resampled.index[-1])

    X, y = build_features(resampled, LAG_WINDOW)
    log.info("  Feature matrix: %s  (lag=%d + 2 time features)", X.shape, LAG_WINDOW)

    model = XGBRegressor(
        n_estimators=XGB_N_ESTIMATORS,
        max_depth=XGB_MAX_DEPTH,
        learning_rate=XGB_LEARNING_RATE,
        tree_method="hist",
        verbosity=0,
    )
    model.fit(X, y)

    preds = model.predict(X)
    residuals = y - preds
    res_mean = float(residuals.mean())
    res_std = float(residuals.std())
    threshold = ANOMALY_Z_THRESHOLD * res_std

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{signal_name}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(model, f)

    log.info(
        "  residual_mean=%.4f  residual_std=%.4f  threshold=±%.4f",
        res_mean, res_std, threshold,
    )
    log.info("  Saved → %s", model_path)

    return {"mean": res_mean, "std": res_std}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train XGBoost models for EMS anomaly detection"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Train all configured signals")
    group.add_argument("--signal", metavar="NAME", help="Train a single signal by name")
    args = parser.parse_args()

    if args.all:
        signals_to_train = SIGNALS
    elif args.signal in SIGNALS:
        signals_to_train = {args.signal: SIGNALS[args.signal]}
    else:
        log.error("Unknown signal '%s'. Available: %s", args.signal, sorted(SIGNALS))
        sys.exit(1)

    # Load existing stats so we update without overwriting other signals
    stats: dict = {}
    if RESIDUAL_STATS_PATH.exists():
        with open(RESIDUAL_STATS_PATH) as f:
            stats = json.load(f)

    trained = 0
    for name, cfg in signals_to_train.items():
        result = train_signal(name, cfg)
        if result:
            stats[name] = result
            trained += 1

    with open(RESIDUAL_STATS_PATH, "w") as f:
        json.dump(stats, f, indent=2)

    log.info("")
    log.info("Training complete: %d/%d signals trained.", trained, len(signals_to_train))
    log.info("Residual stats → %s", RESIDUAL_STATS_PATH)


if __name__ == "__main__":
    main()
