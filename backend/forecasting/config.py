from __future__ import annotations

from pathlib import Path

_FORECASTING_DIR = Path(__file__).resolve().parent   # backend/forecasting/
_BACKEND_DIR = _FORECASTING_DIR.parent               # backend/

# Signals to model — sensor key + field name
# All three AC load groups + battery signals.
SIGNALS: dict[str, dict[str, str]] = {
    # Load Group 1
    "load1_ac_voltage":   {"sensor": "load1",   "field": "ac_voltage"},
    "load1_ac_current":   {"sensor": "load1",   "field": "ac_current"},
    "load1_active_power": {"sensor": "load1",   "field": "active_power"},
    "load1_frequency":    {"sensor": "load1",   "field": "frequency"},
    # Load Group 2
    "load2_ac_voltage":   {"sensor": "load2",   "field": "ac_voltage"},
    "load2_ac_current":   {"sensor": "load2",   "field": "ac_current"},
    "load2_active_power": {"sensor": "load2",   "field": "active_power"},
    "load2_frequency":    {"sensor": "load2",   "field": "frequency"},
    # Load Group 3
    "load3_ac_voltage":   {"sensor": "load3",   "field": "ac_voltage"},
    "load3_ac_current":   {"sensor": "load3",   "field": "ac_current"},
    "load3_active_power": {"sensor": "load3",   "field": "active_power"},
    "load3_frequency":    {"sensor": "load3",   "field": "frequency"},
    # Battery
    "battery_voltage":    {"sensor": "battery", "field": "battery_voltage"},
    "battery_current":    {"sensor": "battery", "field": "battery_current"},
    "battery_soc":        {"sensor": "battery", "field": "soc"},
}

# XGBoost model parameters
LAG_WINDOW = 5               # number of lag readings used as features
XGB_N_ESTIMATORS = 200
XGB_MAX_DEPTH = 4
XGB_LEARNING_RATE = 0.1

RESAMPLE_INTERVAL = "5s"
INFERENCE_INTERVAL_SECONDS = 5
ANOMALY_Z_THRESHOLD = 3.0
SUSTAINED_ANOMALY_THRESHOLD = 10
MIN_TRAINING_BUCKETS = 300

LOG_DIR = _BACKEND_DIR / "logs"
MODELS_DIR = _FORECASTING_DIR / "models"
RESIDUAL_STATS_PATH = _FORECASTING_DIR / "residual_stats.json"
RESIDUALS_DIR = LOG_DIR / "residuals"
ANOMALIES_PATH = LOG_DIR / "anomalies.jsonl"
