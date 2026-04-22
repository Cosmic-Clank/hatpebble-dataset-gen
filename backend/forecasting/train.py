"""
SARIMA training script — run once to produce model pickles.

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

# Ensure backend/ is on sys.path when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from statsmodels.tsa.statespace.sarimax import SARIMAX

from forecasting.config import (
    ANOMALY_Z_THRESHOLD,
    LOG_DIR,
    MIN_TRAINING_BUCKETS,
    MODELS_DIR,
    RESIDUAL_STATS_PATH,
    SARIMA_ORDER,
    SARIMA_SEASONAL_ORDER,
    SIGNALS,
)
from forecasting.preprocess import load_sensor_logs, resample_to_5s

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("train")


def train_signal(signal_name: str, cfg: dict) -> dict | None:
    sensor = cfg["sensor"]
    field = cfg["field"]

    log.info("── %s  (%s.%s)", signal_name, sensor, field)
    series = load_sensor_logs(sensor, field, LOG_DIR)

    if series.empty:
        log.warning("  No data found — run mock_training_data.py first, then retry.")
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
    log.info("  Fitting SARIMA%s ...", SARIMA_ORDER)

    model = SARIMAX(
        resampled,
        order=SARIMA_ORDER,
        seasonal_order=SARIMA_SEASONAL_ORDER,
        enforce_stationarity=False,
        enforce_invertibility=False,
    )
    results = model.fit(disp=False)

    in_sample = results.fittedvalues
    residuals = resampled - in_sample
    res_mean = float(residuals.mean())
    res_std = float(residuals.std())
    threshold = ANOMALY_Z_THRESHOLD * res_std
    train_end_ts = resampled.index[-1].isoformat()

    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    model_path = MODELS_DIR / f"{signal_name}.pkl"
    with open(model_path, "wb") as f:
        pickle.dump(results, f)

    log.info(
        "  AIC=%.1f  residual_mean=%.4f  residual_std=%.4f  threshold=±%.4f",
        results.aic, res_mean, res_std, threshold,
    )
    log.info("  Saved → %s", model_path)

    return {"mean": res_mean, "std": res_std, "train_end_ts": train_end_ts}


def main() -> None:
    parser = argparse.ArgumentParser(description="Train SARIMA models for EMS anomaly detection")
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

    # Load existing stats so we can update without overwriting other signals
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
