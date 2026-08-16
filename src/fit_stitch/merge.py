"""Merge N Garmin FIT activity files into one continuous activity.

Strategy: copy each file's full decoded record stream (definition messages
included, so undocumented Garmin messages survive), dropping per-file
session/activity/file_id/file_creator structures, while running offsets make
each file continue where the previous one ended (distance, accumulated power,
lap and split numbering). One session and one activity are rebuilt at the end
and the result is re-encoded with a fresh header and CRC.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from fit_tool.data_message import DataMessage
from fit_tool.definition_message import DefinitionMessage
from fit_tool.fit_file import FitFile
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.profile_type import Sport

from fit_stitch.constants import (
    ACTIVITY,
    FILE_CREATOR,
    FILE_ID,
    LAP,
    RECORD,
    SENTINELS,
    SESSION,
    SPLIT,
    SPLIT_SUMMARY,
    TIME_IN_ZONE,
)
from fit_stitch.fields import fset, fval, is_session_scoped_tiz, merge_summary
from fit_stitch.session import rebuild_activity, rebuild_session

log = logging.getLogger(__name__)


class MergeError(Exception):
    """Raised when the input files cannot be merged into one activity."""


@dataclass
class MergeStats:
    """Summary of a completed merge, for CLI reporting and tests."""

    files: int = 0
    records: int = 0
    laps: int = 0
    splits: int = 0
    total_distance: float = 0.0
    total_timer_time: float = 0.0
    total_elapsed_time: float = 0.0
    normalized_power: int | None = None
    dropped: dict = field(default_factory=dict)
    sources: list[dict] = field(default_factory=list)  # per-input session summaries
    merged: dict = field(default_factory=dict)  # merged session summary


def sport_name(value) -> str:
    """Human-readable sport name for a FIT sport enum value."""
    if value is None:
        return "unknown"
    try:
        return Sport(value).name.lower()
    except ValueError:
        return f"sport_{value}"


def _session_summary(msg) -> dict:
    """Basic parameters of a session message, with invalid sentinels as None."""

    def v(name):
        x = fval(msg, name)
        return None if isinstance(x, int) and x in SENTINELS else x

    return {
        "sport": sport_name(v("sport")),
        "start_ms": v("start_time"),
        "distance_m": v("total_distance"),
        "elapsed_s": v("total_elapsed_time"),
        "timer_s": v("total_timer_time"),
        "avg_speed_ms": v("enhanced_avg_speed") or v("avg_speed"),
        "avg_power": v("avg_power"),
        "max_power": v("max_power"),
        "normalized_power": v("normalized_power"),
        "avg_hr": v("avg_heart_rate"),
        "max_hr": v("max_heart_rate"),
        "ascent_m": v("total_ascent"),
        "calories": v("total_calories"),
    }


def _decode_sorted(paths: list[Path]) -> list[tuple[Path, FitFile]]:
    decoded = []
    for n, p in enumerate(paths, start=1):
        log.info("decoding %d/%d: %s (%.1f MB)", n, len(paths), p.name, p.stat().st_size / 1e6)
        fit = FitFile.from_file(str(p))
        log.info("  %d messages", len(fit.records))
        session_msgs = [
            r.message
            for r in fit.records
            if isinstance(r.message, DataMessage) and r.message.global_id == SESSION
        ]
        if len(session_msgs) != 1:
            raise MergeError(
                f"{p}: expected exactly 1 session message, found {len(session_msgs)} "
                "(is this a single-activity FIT file?)"
            )
        decoded.append((p, fit, session_msgs[0]))

    sports = {fval(s, "sport") for _, _, s in decoded if fval(s, "sport") is not None}
    if len(sports) > 1:
        detail = ", ".join(f"{p.name}={sport_name(fval(s, 'sport'))}" for p, _, s in decoded)
        raise MergeError(f"cannot merge different activity types: {detail}")

    decoded.sort(key=lambda t: fval(t[2], "start_time"))
    log.info("chronological order: %s", " -> ".join(p.name for p, _, _ in decoded))
    for (p1, _, s1), (p2, _, s2) in zip(decoded, decoded[1:], strict=False):
        end1 = fval(s1, "start_time") + round(fval(s1, "total_elapsed_time") * 1000)
        if fval(s2, "start_time") < end1:
            raise MergeError(f"activities overlap in time: {p1.name} and {p2.name}")
    return [(p, fit) for p, fit, _ in decoded]


def merge_files(paths: list[Path], out: Path) -> MergeStats:
    """Merge the given FIT activity files (2+) into ``out``. Returns MergeStats."""
    if len(paths) < 2:
        raise MergeError("need at least 2 input files")

    stats = MergeStats(files=len(paths), dropped={"session_time_in_zone": 0})
    out_msgs = []
    sessions = []
    activity1 = None
    powers: list[int] = []

    dist_offset = 0.0
    accum_power_offset = None
    lap_count = 0
    split_count = 0
    split_summaries: dict = {}  # split_type -> (message, accumulated weight)

    for i, (path, fit) in enumerate(_decode_sorted(paths)):
        last_dist = None
        last_accum_power = None
        file_laps = 0
        file_splits = 0

        for rec in fit.records:
            m = rec.message
            if isinstance(m, DefinitionMessage):
                out_msgs.append(m)
                continue
            gid = m.global_id

            if gid == SESSION:
                sessions.append(m)
                stats.sources.append({"name": path.name, **_session_summary(m)})
                continue
            if gid == ACTIVITY:
                if i == 0:
                    activity1 = m
                continue
            if gid in (FILE_ID, FILE_CREATOR) and i > 0:
                continue
            if gid == TIME_IN_ZONE:
                if is_session_scoped_tiz(m):
                    stats.dropped["session_time_in_zone"] += 1
                    continue
                if i > 0:
                    ri = fval(m, "reference_index")
                    if ri is not None:
                        fset(m, "reference_index", ri + lap_count)
            elif gid == LAP:
                fset(m, "message_index", lap_count + file_laps)
                file_laps += 1
            elif gid == SPLIT:
                if i > 0:
                    mi = fval(m, "message_index")
                    if mi is not None:
                        fset(m, "message_index", mi + split_count)
                file_splits += 1
            elif gid == SPLIT_SUMMARY:
                st = fval(m, "split_type")
                w_new = fval(m, "total_timer_time") or 1.0
                if st is not None and st in split_summaries:
                    existing, w_acc = split_summaries[st]
                    merge_summary(existing, m, w_acc, w_new)
                    split_summaries[st] = (existing, w_acc + w_new)
                    continue  # folded into the earlier message; drop this one
                if st is not None:
                    split_summaries[st] = (m, w_new)
            elif gid == RECORD:
                stats.records += 1
                d = fval(m, "distance")
                if d is not None:
                    if i > 0:
                        d += dist_offset
                        fset(m, "distance", d)
                    last_dist = d
                ap = fval(m, "accumulated_power")
                if ap is not None:
                    if i > 0 and accum_power_offset is not None:
                        ap += accum_power_offset
                        fset(m, "accumulated_power", ap)
                    last_accum_power = ap
                p = fval(m, "power")
                if p is not None:
                    powers.append(p)

            out_msgs.append(m)

        if last_dist is None:
            raise MergeError(f"{path}: no distance data in record messages")
        log.info(
            "merged %s: %d laps, %d splits, distance now %.2f km",
            path.name,
            file_laps,
            file_splits,
            last_dist / 1000,
        )
        dist_offset = last_dist
        if last_accum_power is not None:
            accum_power_offset = last_accum_power
        lap_count += file_laps
        split_count += file_splits

    if activity1 is None:
        raise MergeError(f"{paths[0]}: no activity message found in first file")

    log.info("rebuilding session/activity from %d source sessions", len(sessions))
    merged_session, end_ms = rebuild_session(sessions, powers, lap_count)
    out_msgs.append(merged_session)
    total_timer = fval(merged_session, "total_timer_time")
    out_msgs.append(rebuild_activity(activity1, end_ms, total_timer))

    log.info("encoding %d messages -> %s", len(out_msgs), out)
    builder = FitFileBuilder(auto_define=True, min_string_size=0)
    builder.add_all(out_msgs)
    builder.build().to_file(str(out))
    log.info("wrote %s (%.1f MB)", out, out.stat().st_size / 1e6)

    stats.merged = {"name": "merged", **_session_summary(merged_session)}
    stats.laps = lap_count
    stats.splits = split_count
    stats.total_distance = fval(merged_session, "total_distance")
    stats.total_timer_time = total_timer
    stats.total_elapsed_time = fval(merged_session, "total_elapsed_time")
    stats.normalized_power = fval(merged_session, "normalized_power")
    return stats
