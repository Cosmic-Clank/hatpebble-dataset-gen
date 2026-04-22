"""
Fast synthetic training data generator.

Generates historical telemetry in the same CSV format that main.py writes,
using the same math as mock_esp.py — no sleeping, runs as fast as the CPU allows.

Usage:
    python mock_training_data.py                  # 2 hours of data (default)
    python mock_training_data.py --seconds 3600   # 1 hour
    python mock_training_data.py --seconds 14400  # 4 hours
"""

from __future__ import annotations

import argparse
import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

INTERVAL = 0.5  # seconds between simulated readings (same as mock_esp.py)

LOAD_PROFILES = {
    "load1": {"base_current": 10, "base_pf": 0.95},
    "load2": {"base_current": 6,  "base_pf": 0.88},
    "load3": {"base_current": 14, "base_pf": 0.99},
}

LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

BATTERY_COLUMNS = [
    "timestamp", "time", "battery_voltage", "battery_current",
    "battery_power", "soc", "consumed_ah", "time_to_go",
    "alarm_flags", "temperature",
]

AC_COLUMNS = [
    "timestamp", "date", "time", "ac_voltage", "ac_current",
    "active_power", "active_energy", "frequency", "power_factor",
]


def _open_csv(sensor: str, today: str) -> tuple[csv.writer, object]:
    filepath = LOG_DIR / f"{sensor}_{today}.csv"
    is_new = not filepath.exists()
    fh = open(filepath, "a", newline="", encoding="utf-8")
    writer = csv.writer(fh)
    columns = BATTERY_COLUMNS if sensor == "battery" else AC_COLUMNS
    if is_new:
        writer.writerow(columns)
    return writer, fh


def generate(total_seconds: int) -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    start_ts = datetime.now(timezone.utc) - timedelta(seconds=total_seconds)

    writers: dict[str, tuple[csv.writer, object]] = {}
    for sensor in ["battery"] + list(LOAD_PROFILES.keys()):
        writers[sensor] = _open_csv(sensor, today)

    energy_acc: dict[str, float] = {lg: 0.0 for lg in LOAD_PROFILES}
    steps = int(total_seconds / INTERVAL)

    print(f"Generating {steps:,} steps ({total_seconds}s) of synthetic data...")

    for step in range(steps):
        t = step * INTERVAL
        ts = start_ts + timedelta(seconds=t)
        ts_iso = ts.isoformat()
        sim_time = round(t, 1)
        sim_date = ts.strftime("%Y-%m-%d")
        sim_hms = ts.strftime("%H:%M:%S")

        # --- Battery ---
        voltage = 12.8 + 0.3 * math.sin(t / 60) + random.uniform(-0.05, 0.05)
        current = -3.0 + 1.5 * math.sin(t / 30) + random.uniform(-0.2, 0.2)
        power = voltage * current
        soc = max(0.0, min(100.0, 85 + 15 * math.sin(t / 120)))
        temperature = 25 + 3 * math.sin(t / 90) + random.uniform(-0.5, 0.5)

        batt_row = [
            ts_iso, sim_time,
            round(voltage, 4), round(current, 4), round(power, 4),
            round(soc, 1), round(abs(current) * t / 3600, 2),
            round(max(0, soc / max(0.1, abs(current))) * 0.5, 1),
            None, round(temperature, 2),
        ]
        writers["battery"][0].writerow(batt_row)

        # --- AC loads ---
        for lg, profile in LOAD_PROFILES.items():
            phase_offset = hash(lg) % 60
            ac_voltage = 230 + 10 * math.sin(t / 45) + random.uniform(-2, 2)
            ac_current = (
                profile["base_current"]
                + (profile["base_current"] * 0.3) * math.sin((t + phase_offset) / 20)
                + random.uniform(-0.3, 0.3)
            )
            pf = profile["base_pf"] + 0.03 * math.sin(t / 40) + random.uniform(-0.01, 0.01)
            pf = min(1.0, max(0.0, pf))
            active_power = ac_voltage * ac_current * pf
            energy_acc[lg] += active_power * INTERVAL / 3_600_000
            frequency = 50.0 + random.uniform(-0.05, 0.05)

            ac_row = [
                ts_iso, sim_date, sim_hms,
                round(ac_voltage, 1), round(ac_current, 2),
                round(active_power, 1), round(energy_acc[lg], 6),
                round(frequency, 2), round(pf, 2),
            ]
            writers[lg][0].writerow(ac_row)

        if step % 10000 == 0 and step > 0:
            print(f"  {step:,}/{steps:,} steps ({100*step//steps}%)")

    for writer, fh in writers.values():
        fh.flush()
        fh.close()

    print(f"Done. Files written to {LOG_DIR}/")
    for sensor in ["battery"] + list(LOAD_PROFILES.keys()):
        filepath = LOG_DIR / f"{sensor}_{today}.csv"
        size_kb = filepath.stat().st_size / 1024
        print(f"  {filepath.name}: {size_kb:.0f} KB")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate synthetic EMS training data")
    parser.add_argument(
        "--seconds", type=int, default=7200,
        help="Seconds of simulated history to generate (default: 7200 = 2h)"
    )
    args = parser.parse_args()
    generate(args.seconds)
