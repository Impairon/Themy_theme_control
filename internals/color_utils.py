"""Small color-shape helpers shared by the GUI and its tests."""
from __future__ import annotations

from typing import Any


def hex_color(value: Any, fallback: str) -> str:
    """Read plain and Matugen nested hex color values."""
    if isinstance(value, dict):
        for key in ("hex", "color", "hex_stripped"):
            if key in value:
                inner = value[key]
                if isinstance(inner, str) and inner:
                    return hex_color(inner, fallback)
        if "default" in value:
            return hex_color(value["default"], fallback)
        if all(key in value for key in ("red", "green", "blue")):
            value = "#{:02x}{:02x}{:02x}".format(
                int(value["red"]), int(value["green"]), int(value["blue"])
            )
    value = str(value or "").strip()
    if len(value) == 7 and value.startswith("#"):
        try:
            int(value[1:], 16)
            return value.lower()
        except ValueError:
            pass
    if len(value) == 6:
        try:
            int(value, 16)
            return "#" + value.lower()
        except ValueError:
            pass
    return fallback
