"""Human-readable values for notification text.

Storage, MQTT and the API are SI only. Phone notifications are a display surface, like
the GUI, so this is the one place the backend converts to the user's chosen units.
"""

from __future__ import annotations


def format_value(kind: str, value: float, display_units: str) -> str:
    if kind == "temperature":
        if display_units == "imperial":
            return f"{value * 9 / 5 + 32:.1f} °F"
        return f"{value:.1f} °C"
    if kind in ("humidity", "soil_moisture"):
        return f"{value:.0f} %"
    if kind == "illuminance":
        return f"{value:.0f} lx"
    return f"{value:g}"
