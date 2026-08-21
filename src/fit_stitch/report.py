"""Formatting for the source-vs-merged comparison table.

The CLI draws this table with box characters and the web UI renders it as HTML,
but both must show the same rows in the same units. Keeping the row spec and the
formatters here means a unit is defined once; callers only decide how to draw the
cells they are handed.
"""

import datetime

MISSING = "—"


def fmt_duration(seconds: float) -> str:
    """H:MM:SS, with hours unpadded (rides run past 9 hours)."""
    seconds = round(seconds)
    return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"


def fmt_start(ms: int) -> str:
    """Wall-clock start time in UTC."""
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%H:%M:%S")


# Session-summary key -> (row label, value formatter). Order is display order.
COMPARISON_ROWS = {
    "sport": ("sport", str),
    "start_ms": ("start (UTC)", fmt_start),
    "distance_m": ("distance", lambda m: f"{m / 1000:.2f} km"),
    "timer_s": ("moving time", fmt_duration),
    "elapsed_s": ("elapsed time", fmt_duration),
    "avg_speed_ms": ("avg speed", lambda v: f"{v * 3.6:.1f} km/h"),
    "avg_power": ("avg power", lambda v: f"{v} W"),
    "max_power": ("max power", lambda v: f"{v} W"),
    "normalized_power": ("norm power", lambda v: f"{v} W"),
    "avg_hr": ("avg HR", lambda v: f"{v} bpm"),
    "max_hr": ("max HR", lambda v: f"{v} bpm"),
    "ascent_m": ("ascent", lambda v: f"{v} m"),
    "calories": ("calories", lambda v: f"{v} kcal"),
}


def build_comparison(stats) -> dict:
    """Formatted table body: one column per source activity, then the merged one.

    Rows where no column has a value are dropped, so a ride recorded without a
    power meter shows no power rows at all rather than a block of dashes.
    """
    columns = [*stats.sources, stats.merged]
    rows = []
    for key, (label, fmt) in COMPARISON_ROWS.items():
        values = [MISSING if c.get(key) is None else fmt(c[key]) for c in columns]
        if any(v != MISSING for v in values):
            rows.append({"label": label, "values": values})
    return {"columns": [c["name"] for c in columns], "rows": rows}
