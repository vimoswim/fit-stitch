"""Merge N Garmin FIT activity files into one continuous activity.

Strategy: copy each file's full decoded record stream (definition messages
included, so undocumented Garmin messages survive), dropping per-file
session/activity/file_id/file_creator structures, while running offsets make
each file continue where the previous one ended (distance, accumulated power,
lap and split numbering). One session and one activity are rebuilt at the end
and the result is re-encoded with a fresh header and CRC.
"""

from dataclasses import dataclass, field
from pathlib import Path

from fit_tool.data_message import DataMessage
from fit_tool.definition_message import DefinitionMessage
from fit_tool.fit_file import FitFile
from fit_tool.fit_file_builder import FitFileBuilder

from fit_stitch.constants import (
    ACTIVITY,
    EVENT,
    FILE_CREATOR,
    FILE_ID,
    LAP,
    RECORD,
    SESSION,
    SPLIT,
    SPLIT_SUMMARY,
    TIME_IN_ZONE,
)
from fit_stitch.fields import fset, fval, is_session_scoped_tiz, merge_summary
from fit_stitch.session import rebuild_activity, rebuild_session


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


def _decode_sorted(paths: list[Path]) -> list[tuple[Path, FitFile]]:
    decoded = []
    for p in paths:
        fit = FitFile.from_file(str(p))
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

    decoded.sort(key=lambda t: fval(t[2], "start_time"))
    for (p1, _, s1), (p2, _, s2) in zip(decoded, decoded[1:]):
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
        dist_offset = last_dist
        if last_accum_power is not None:
            accum_power_offset = last_accum_power
        lap_count += file_laps
        split_count += file_splits

    if activity1 is None:
        raise MergeError(f"{paths[0]}: no activity message found in first file")

    merged_session, end_ms = rebuild_session(sessions, powers, lap_count)
    out_msgs.append(merged_session)
    total_timer = fval(merged_session, "total_timer_time")
    out_msgs.append(rebuild_activity(activity1, end_ms, total_timer))

    builder = FitFileBuilder(auto_define=True, min_string_size=0)
    builder.add_all(out_msgs)
    builder.build().to_file(str(out))

    stats.laps = lap_count
    stats.splits = split_count
    stats.total_distance = fval(merged_session, "total_distance")
    stats.total_timer_time = total_timer
    stats.total_elapsed_time = fval(merged_session, "total_elapsed_time")
    stats.normalized_power = fval(merged_session, "normalized_power")
    return stats
