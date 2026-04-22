from __future__ import annotations

from pathlib import Path

import pandas as pd

from .config import RESAMPLE_INTERVAL


def load_sensor_logs(sensor_key: str, signal_field: str, log_dir: Path) -> pd.Series:
    """Read all daily CSVs for a sensor, return a time-indexed Series for one field."""
    files = sorted(log_dir.glob(f"{sensor_key}_*.csv"))
    if not files:
        return pd.Series(dtype=float, name=signal_field)

    frames: list[pd.Series] = []
    for f in files:
        try:
            df = pd.read_csv(f, parse_dates=["timestamp"])
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).set_index("timestamp")
            if signal_field in df.columns:
                col = pd.to_numeric(df[signal_field], errors="coerce").dropna()
                frames.append(col)
        except Exception:
            continue

    if not frames:
        return pd.Series(dtype=float, name=signal_field)

    combined = pd.concat(frames).sort_index()
    combined.name = signal_field
    return combined


def load_sensor_logs_since(
    sensor_key: str,
    signal_field: str,
    log_dir: Path,
    since_ts: pd.Timestamp | None = None,
) -> pd.Series:
    """Read only today's CSV, optionally filtering to rows after since_ts."""
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    filepath = log_dir / f"{sensor_key}_{today}.csv"
    if not filepath.exists():
        return pd.Series(dtype=float, name=signal_field)

    try:
        df = pd.read_csv(filepath, parse_dates=["timestamp"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["timestamp"]).set_index("timestamp")
        if signal_field not in df.columns:
            return pd.Series(dtype=float, name=signal_field)
        col = pd.to_numeric(df[signal_field], errors="coerce").dropna()
        if since_ts is not None:
            col = col[col.index > since_ts]
        col.name = signal_field
        return col
    except Exception:
        return pd.Series(dtype=float, name=signal_field)


def resample_to_5s(series: pd.Series) -> pd.Series:
    """Resample a time-indexed Series to RESAMPLE_INTERVAL buckets."""
    if series.empty:
        return series
    resampled = series.resample(RESAMPLE_INTERVAL).mean().dropna()
    resampled.name = series.name
    return resampled
