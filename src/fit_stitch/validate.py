"""Validate a FIT activity file with the official Garmin FIT SDK decoder."""

import datetime
from dataclasses import dataclass, field
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream


@dataclass
class ValidationReport:
    """Outcome of all checks plus headline stats of the file."""

    checks: list[tuple[str, bool, str]] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return all(passed for _, passed, _ in self.checks)

    def add(self, name: str, passed: bool, detail: str = ""):
        self.checks.append((name, passed, detail))


def _decode(path: Path):
    stream = Stream.from_file(str(path))
    decoder = Decoder(stream)
    is_fit = decoder.is_fit()
    stream.reset()
    integrity = Decoder(stream).check_integrity() if is_fit else False
    stream.reset()
    messages, errors = Decoder(stream).read()
    return is_fit, integrity, messages, errors


def validate_fit(path: Path, expected_sources: list[Path] | None = None) -> ValidationReport:
    """Run structural checks; with ``expected_sources``, also cross-check coverage."""
    report = ValidationReport()
    is_fit, integrity, messages, errors = _decode(path)
    report.add("is_fit", is_fit)
    report.add("crc_integrity", integrity)
    report.add("decode_errors", not errors, f"{errors}" if errors else "none")
    if not is_fit:
        return report

    recs = messages.get("record_mesgs", [])
    sessions = messages.get("session_mesgs", [])
    activities = messages.get("activity_mesgs", [])
    laps = messages.get("lap_mesgs", [])

    chrono = all(recs[i]["timestamp"] <= recs[i + 1]["timestamp"] for i in range(len(recs) - 1))
    report.add("records_chronological", chrono)

    dists = [r["distance"] for r in recs if r.get("distance") is not None]
    mono = all(dists[i] <= dists[i + 1] + 1e-9 for i in range(len(dists) - 1))
    report.add(
        "distance_monotonic",
        mono and bool(dists),
        f"first={dists[0]} last={dists[-1]}" if dists else "no distance data",
    )

    report.add("one_session", len(sessions) == 1, f"found {len(sessions)}")
    report.add("one_activity", len(activities) == 1, f"found {len(activities)}")

    lap_idx = [lap.get("message_index") for lap in laps]
    report.add("lap_indices_continuous", lap_idx == list(range(len(laps))), f"{len(laps)} laps")

    if not sessions:
        return report
    s = sessions[0]
    sess_start = s["start_time"]
    sess_end = sess_start + datetime.timedelta(seconds=s["total_elapsed_time"])

    if expected_sources:
        src_dist = 0.0
        covers = True
        for src in expected_sources:
            _, _, sm, _ = _decode(src)
            sr = sm.get("record_mesgs", [])
            if not sr:
                covers = False
                continue
            covers = covers and sess_start <= sr[0]["timestamp"] and sr[-1]["timestamp"] <= sess_end
            src_dist += sr[-1].get("distance") or 0.0
        report.add("session_covers_sources", covers)
        diff = abs((s.get("total_distance") or 0.0) - src_dist)
        report.add("distance_matches_sources", diff < 0.01, f"diff={diff:.4f} m")

    report.stats = {
        "start_time": s["start_time"],
        "end_time": sess_end,
        "total_elapsed_time_s": s.get("total_elapsed_time"),
        "total_timer_time_s": s.get("total_timer_time"),
        "total_distance_m": s.get("total_distance"),
        "records": len(recs),
        "laps": len(laps),
        "avg_heart_rate": s.get("avg_heart_rate"),
        "max_heart_rate": s.get("max_heart_rate"),
        "avg_power": s.get("avg_power"),
        "max_power": s.get("max_power"),
        "normalized_power": s.get("normalized_power"),
        "avg_cadence": s.get("avg_cadence"),
        "max_cadence": s.get("max_cadence"),
        "avg_speed_kmh": round((s.get("enhanced_avg_speed") or 0) * 3.6, 2),
        "max_speed_kmh": round((s.get("enhanced_max_speed") or 0) * 3.6, 2),
        "total_ascent_m": s.get("total_ascent"),
        "total_descent_m": s.get("total_descent"),
        "total_calories": s.get("total_calories"),
    }
    return report
