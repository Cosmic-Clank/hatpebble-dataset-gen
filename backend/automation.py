"""
Rule-based load group automation engine.
Evaluates user-defined rules every 10 seconds and fires relay control
commands via MQTT when conditions are met.

Rule types (time):
  - time               : fire once per day when clock matches HH:MM

Rule types (AC load — reads from latest[load_group]):
  - power_above/below   : active_power (W)
  - voltage_above/below : ac_voltage (V)
  - current_above/below : ac_current (A)
  - frequency_above/below : frequency (Hz)
  - pf_above/below      : power_factor

Rule types (battery — reads from latest["battery"]):
  - soc_above/below         : soc (%)
  - bat_voltage_above/below : battery_voltage (V)
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Awaitable

log = logging.getLogger("ems.automation")

RULES_FILE = Path(__file__).resolve().parent / "automation_rules.json"
EVAL_INTERVAL   = 5    # seconds between evaluation passes
POWER_COOLDOWN  = 60   # seconds before a power rule can re-trigger for the same load

VALID_CONDITION_TYPES = {
    "time",
    "power_above", "power_below",
    "voltage_above", "voltage_below",
    "current_above", "current_below",
    "frequency_above", "frequency_below",
    "pf_above", "pf_below",
    "soc_above", "soc_below",
    "bat_voltage_above", "bat_voltage_below",
}
VALID_ACTIONS = {"ON", "OFF"}

# Maps threshold condition_type → (sensor_source, field_name, direction)
# sensor_source "load" reads from latest[load_group]; "battery" reads from latest["battery"]
_THRESHOLD_MAP: dict[str, tuple[str, str, str]] = {
    "power_above":       ("load",    "active_power",    "above"),
    "power_below":       ("load",    "active_power",    "below"),
    "voltage_above":     ("load",    "ac_voltage",      "above"),
    "voltage_below":     ("load",    "ac_voltage",      "below"),
    "current_above":     ("load",    "ac_current",      "above"),
    "current_below":     ("load",    "ac_current",      "below"),
    "frequency_above":   ("load",    "frequency",       "above"),
    "frequency_below":   ("load",    "frequency",       "below"),
    "pf_above":          ("load",    "power_factor",    "above"),
    "pf_below":          ("load",    "power_factor",    "below"),
    "soc_above":         ("battery", "soc",             "above"),
    "soc_below":         ("battery", "soc",             "below"),
    "bat_voltage_above": ("battery", "battery_voltage", "above"),
    "bat_voltage_below": ("battery", "battery_voltage", "below"),
}

# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------

_rules: list[dict] = []

# time rules:  rule_id → "YYYY-MM-DD HH:MM" of last fire
_time_last_fired: dict[str, str] = {}

# power rules: rule_id → monotonic time until which the rule is on cooldown
_power_cooldown_until: dict[str, float] = {}

# Injected by main.py
_fire_relay_cb: Callable[[str, str], Awaitable[None]] | None = None
_get_latest_cb: Callable[[], dict[str, Any | None]] | None = None


def set_context(
    fire_relay: Callable[[str, str], Awaitable[None]],
    get_latest: Callable[[], dict[str, Any | None]],
) -> None:
    """Called once from main.py startup to inject MQTT + sensor callbacks."""
    global _fire_relay_cb, _get_latest_cb
    _fire_relay_cb = fire_relay
    _get_latest_cb = get_latest


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def _load() -> None:
    global _rules
    if not RULES_FILE.exists():
        _rules = []
        return
    try:
        with open(RULES_FILE, "r", encoding="utf-8") as f:
            _rules = json.load(f)
        log.info("Loaded %d automation rule(s) from %s", len(_rules), RULES_FILE)
    except Exception as exc:
        log.error("Could not load automation rules: %s", exc)
        _rules = []


def _save() -> None:
    try:
        with open(RULES_FILE, "w", encoding="utf-8") as f:
            json.dump(_rules, f, indent=2)
    except Exception as exc:
        log.error("Could not save automation rules: %s", exc)


# ---------------------------------------------------------------------------
# CRUD helpers (called from REST endpoints in main.py)
# ---------------------------------------------------------------------------

def get_rules(load_group: str | None = None) -> list[dict]:
    if load_group:
        return [r for r in _rules if r.get("load_group") == load_group]
    return list(_rules)


def create_rule(
    load_group: str,
    name: str,
    condition_type: str,
    condition_value: str,
    action: str,
) -> dict:
    rule: dict = {
        "id":              uuid.uuid4().hex,
        "load_group":      load_group,
        "name":            name.strip() or "Unnamed rule",
        "enabled":         True,
        "condition_type":  condition_type,
        "condition_value": condition_value.strip(),
        "action":          action.upper(),
        "created_at":      datetime.now(timezone.utc).isoformat(),
    }
    _rules.append(rule)
    _save()
    log.info("Rule created: %s", rule)
    return rule


def delete_rule(rule_id: str) -> bool:
    global _rules
    before = len(_rules)
    _rules = [r for r in _rules if r.get("id") != rule_id]
    if len(_rules) < before:
        _save()
        return True
    return False


def set_rule_enabled(rule_id: str, enabled: bool) -> dict | None:
    for rule in _rules:
        if rule.get("id") == rule_id:
            rule["enabled"] = enabled
            _save()
            return rule
    return None


# ---------------------------------------------------------------------------
# Evaluation engine
# ---------------------------------------------------------------------------

def _evaluate_once() -> None:
    if _get_latest_cb is None or _fire_relay_cb is None:
        return

    latest = _get_latest_cb()
    now = datetime.now(timezone.utc)
    now_hhmm         = now.strftime("%H:%M")
    now_date_hhmm    = now.strftime("%Y-%m-%d %H:%M")
    now_mono         = time.monotonic()

    for rule in list(_rules):
        if not rule.get("enabled", True):
            continue

        rid    = rule["id"]
        lg     = rule["load_group"]
        ctype  = rule["condition_type"]
        cval   = rule["condition_value"]
        action = rule["action"]
        should_fire = False

        try:
            if ctype == "time":
                if cval == now_hhmm and _time_last_fired.get(rid) != now_date_hhmm:
                    should_fire = True
                    _time_last_fired[rid] = now_date_hhmm

            elif ctype in _THRESHOLD_MAP:
                if now_mono < _power_cooldown_until.get(rid, 0.0):
                    continue
                source, field, direction = _THRESHOLD_MAP[ctype]
                reading = latest.get("battery" if source == "battery" else lg)
                if reading is None:
                    continue
                value = reading.get(field)
                if value is None:
                    continue
                threshold = float(cval)
                if direction == "above" and float(value) > threshold:
                    should_fire = True
                elif direction == "below" and float(value) < threshold:
                    should_fire = True
                if should_fire:
                    _power_cooldown_until[rid] = now_mono + POWER_COOLDOWN

        except Exception as exc:
            log.warning("Rule '%s' evaluation error: %s", rule.get("name"), exc)
            continue

        if should_fire:
            log.info(
                "Automation rule '%s' fired → %s relay %s",
                rule.get("name"), lg, action,
            )
            asyncio.create_task(_fire_relay_cb(lg, action))


# ---------------------------------------------------------------------------
# Background task entry-point
# ---------------------------------------------------------------------------

async def run_forever() -> None:
    _load()
    while True:
        await asyncio.sleep(EVAL_INTERVAL)
        try:
            _evaluate_once()
        except Exception as exc:
            log.error("Automation evaluation error: %s", exc)
