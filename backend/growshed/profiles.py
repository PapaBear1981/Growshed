"""Crop profiles: sensible starting limits for a kind of plant, applied to one zone.

These are typical hobby-hydroponics ranges, not guarantees. Applying a profile just fills
in the tunables for that zone; every value can still be changed afterwards.

Only crops that suit the cheap EC board (reliable up to about 2 mS/cm) are listed.
"""

from __future__ import annotations

from . import db
from .config import SiteConfig
from .tunables import Tunables, alert_key

# (sensor kind, "above" | "below") -> alert limit in SI units; "dosing" -> dosing targets.
PROFILES: dict[str, dict] = {
    "Lettuce and leafy greens": {
        ("temperature", "above", "air"): 27, ("temperature", "below", "air"): 13,
        ("humidity", "above", "air"): 75,
        ("temperature", "above", "water"): 24, ("temperature", "below", "water"): 16,
        ("ph", "below", None): 5.3, ("ph", "above", None): 6.7,
        ("ec", "below", None): 600, ("ec", "above", None): 1800,
        "dosing": {"ph_low": 5.6, "ph_high": 6.2, "ec_low": 800},
    },
    "Herbs (basil, mint, parsley)": {
        ("temperature", "above", "air"): 29, ("temperature", "below", "air"): 16,
        ("humidity", "above", "air"): 70,
        ("temperature", "above", "water"): 24, ("temperature", "below", "water"): 17,
        ("ph", "below", None): 5.3, ("ph", "above", None): 6.7,
        ("ec", "below", None): 700, ("ec", "above", None): 2000,
        "dosing": {"ph_low": 5.6, "ph_high": 6.3, "ec_low": 1000},
    },
    "Strawberries": {
        ("temperature", "above", "air"): 27, ("temperature", "below", "air"): 13,
        ("humidity", "above", "air"): 70,
        ("temperature", "above", "water"): 22, ("temperature", "below", "water"): 15,
        ("ph", "below", None): 5.3, ("ph", "above", None): 6.5,
        ("ec", "below", None): 700, ("ec", "above", None): 1800,
        "dosing": {"ph_low": 5.6, "ph_high": 6.1, "ec_low": 1000},
    },
}  # fmt: skip
WATER_ZONES = ("rdwc", "tower")


def apply_profile(tunables: Tunables, site: SiteConfig, zone_id: str, name: str) -> int:
    """Set every matching limit in one zone (and the zones inside it). Returns how many changed."""
    profile = PROFILES.get(name)
    zones = {z.id: z for z in site.zones}
    if profile is None or zone_id not in zones:
        raise ValueError("Unknown crop profile or zone.")
    family = [zone_id] + [z.id for z in site.zones if z.parent == zone_id]
    changed = 0
    for rule in site.alerts.rules:
        if rule.when_on is not None:
            continue
        direction = "above" if rule.above is not None else "below"
        for zid in family:
            medium = "water" if zones[zid].kind in WATER_ZONES else "air"
            value = profile.get((rule.sensor_kind, direction, medium))
            if value is None:
                value = profile.get((rule.sensor_kind, direction, None))
            key = alert_key(rule.name, zid)
            if value is not None and key in tunables.defs:
                tunables.set(key, value)
                changed += 1
    if site.dosing is not None and site.dosing.zone in family:
        # Widen first, then narrow, so the "0.4 pH apart" check never trips half-way.
        tunables.set("dosing.ph_low", 4.0)
        tunables.set("dosing.ph_high", profile["dosing"]["ph_high"])
        tunables.set("dosing.ph_low", profile["dosing"]["ph_low"])
        tunables.set("dosing.ec_low", profile["dosing"]["ec_low"])
        changed += 3
    db.set_setting(tunables.conn, f"profile:{zone_id}", name)
    return changed


def current_profiles(tunables: Tunables, site: SiteConfig) -> dict[str, str]:
    return {z.id: db.get_setting(tunables.conn, f"profile:{z.id}", "") for z in site.zones}
