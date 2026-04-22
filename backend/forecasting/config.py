from __future__ import annotations

from pathlib import Path

_FORECASTING_DIR = Path(__file__).resolve().parent   # backend/forecasting/
_BACKEND_DIR = _FORECASTING_DIR.parent               # backend/

# Signals to model — sensor key + field name
SIGNALS: dict[str, dict[str, str]] = {
    "load1_ac_voltage":   {"sensor": "load1",   "field": "ac_voltage"},
    "load1_ac_current":   {"sensor": "load1",   "field": "ac_current"},
    "load1_active_power": {"sensor": "load1",   "field": "active_power"},
    "load1_frequency":    {"sensor": "load1",   "field": "frequency"},
    "battery_voltage":    {"sensor": "battery", "field": "battery_voltage"},
    "battery_current":    {"sensor": "battery", "field": "battery_current"},
    "battery_soc":        {"sensor": "battery", "field": "soc"},
}

SARIMA_ORDER = (1, 1, 1)
SARIMA_SEASONAL_ORDER = (0, 0, 0, 0)
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
