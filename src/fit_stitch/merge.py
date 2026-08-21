"""Merge N Garmin FIT activity files into one continuous activity.

Strategy: walk each file at the wire level and copy every record through as its
original bytes, rewriting only the few numeric fields the merge actually
changes (distance and accumulated-power offsets, lap and split numbering).
Per-file session/activity/file_id/file_creator structures are dropped; one
session and one activity are rebuilt at the end and appended; the whole stream
is re-emitted under file 1's header with a recomputed CRC.

Records are projected into typed messages only where the merge needs named
field access — sessions, the activity, split summaries and developer-field
descriptions, a handful of messages per file. Everything else, including the
record stream and every undocumented Garmin message, is copied verbatim. That
keeps the preservation guarantee absolute (untouched records are byte-identical
by construction) and keeps multi-hour activities fast: projecting a record
costs ~84 field allocations, which for a 20 000-record file means 20 s and
~800 MB instead of 0.4 s and 65 MB.

Compressed-timestamp records are copied as-is. They resolve against the last
full timestamp seen in the stream, and every input is a standalone FIT file
that establishes its own before using one, so concatenation preserves their
meaning; the output's chronology is checked by ``validate_fit`` regardless.
"""

import logging
import struct
from dataclasses import dataclass, field
from pathlib import Path

from fit_tool.compatibility import project_data_record, register_developer_field
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.profile_type import Sport
from fit_tool.wire import WireDecoder, crc16, rewrite_header_source_bytes
from fit_tool.wire.model import RawDataRecord, RawDefinitionRecord, RawFileHeader

from fit_stitch.constants import (
    ACTIVITY,
    F_MESSAGE_INDEX,
    F_RECORD_ACCUMULATED_POWER,
    F_RECORD_DISTANCE,
    F_RECORD_POWER,
    F_TIZ_REFERENCE_INDEX,
    F_TIZ_REFERENCE_MESG,
    FIELD_DESCRIPTION,
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
from fit_stitch.fields import fval, merge_summary
from fit_stitch.raw import PayloadIndex, RawPatchError
from fit_stitch.session import rebuild_activity, rebuild_session

log = logging.getLogger(__name__)

# distance is stored as centimetres (profile scale 100); the merge works in raw
# wire units, so per-file offsets are accumulated in centimetres too.
DISTANCE_SCALE = 100


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


@dataclass
class _Input:
    """One decoded input file: raw records plus the bits the merge reads by name."""

    path: Path
    header: RawFileHeader
    records: list
    session: object
    registry: dict


class _Pending:
    """A projected message emitted in place but still open to later edits.

    Split summaries are written at the position of their first occurrence but
    keep absorbing later files, so their bytes can only be produced once the
    whole walk is done. The definition is untouched, so the re-encoded payload
    is the same length as the one it replaces.
    """

    __slots__ = ("header_bytes", "message")

    def __init__(self, header_bytes: bytes, message):
        self.header_bytes = header_bytes
        self.message = message

    def to_bytes(self) -> bytes:
        return self.header_bytes + self.message.to_bytes()


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


def _decode(path: Path, n: int, total: int) -> _Input:
    """Wire-decode one file and project only what the merge reads by name."""
    data = path.read_bytes()
    log.info("decoding %d/%d: %s (%.1f MB)", n, total, path.name, len(data) / 1e6)
    document = WireDecoder().decode(data)
    records = [r for segment in document.segments for r in segment.records]
    log.info("  %d messages", len(records))

    registry: dict = {}
    sessions = []
    for rec in records:
        if isinstance(rec, RawDefinitionRecord):
            continue
        gid = rec.definition.global_id
        # Field descriptions must be registered before any message that carries
        # developer fields is projected, so they are collected on this pass.
        if gid == FIELD_DESCRIPTION:
            register_developer_field(project_data_record(rec, registry), registry)
        elif gid == SESSION:
            sessions.append(project_data_record(rec, registry).message)

    if len(sessions) != 1:
        raise MergeError(
            f"{path}: expected exactly 1 session message, found {len(sessions)} "
            "(is this a single-activity FIT file?)"
        )
    return _Input(path, document.segments[0].header, records, sessions[0], registry)


def _decode_sorted(paths: list[Path]) -> list[_Input]:
    """Decode all inputs, reject unmergeable combinations, order chronologically."""
    inputs = [_decode(p, n, len(paths)) for n, p in enumerate(paths, start=1)]

    sports = {fval(i.session, "sport") for i in inputs}
    sports.discard(None)
    if len(sports) > 1:
        detail = ", ".join(f"{i.path.name}={sport_name(fval(i.session, 'sport'))}" for i in inputs)
        raise MergeError(f"cannot merge different activity types: {detail}")

    inputs.sort(key=lambda i: fval(i.session, "start_time"))
    log.info("chronological order: %s", " -> ".join(i.path.name for i in inputs))
    for a, b in zip(inputs, inputs[1:], strict=False):
        end_a = fval(a.session, "start_time") + round(fval(a.session, "total_elapsed_time") * 1000)
        if fval(b.session, "start_time") < end_a:
            raise MergeError(f"activities overlap in time: {a.path.name} and {b.path.name}")
    return inputs


def _encode_tail(messages: list) -> bytes:
    """Serialize the rebuilt session and activity as wire records.

    Built through ``FitFileBuilder`` so definitions and local IDs come from
    fit-tool, then unwrapped with the wire decoder so the file header and CRC of
    that throwaway file are dropped rather than sliced off by hand. Redefining a
    local ID here is safe: nothing follows these records in the merged stream.
    """
    builder = FitFileBuilder(auto_define=True, min_string_size=0)
    builder.add_all(messages)
    document = WireDecoder().decode(builder.build_bytes())
    return b"".join(r.source_bytes for s in document.segments for r in s.records)


def merge_files(paths: list[Path], out: Path) -> MergeStats:
    """Merge the given FIT activity files (2+) into ``out``. Returns MergeStats."""
    if len(paths) < 2:
        raise MergeError("need at least 2 input files")

    stats = MergeStats(files=len(paths), dropped={"session_time_in_zone": 0})
    idx = PayloadIndex()
    parts: list = []
    sessions = []
    activity1 = None
    powers: list[int] = []

    dist_offset = 0  # raw centimetres
    accum_power_offset = None
    lap_count = 0
    split_count = 0
    split_summaries: dict = {}  # split_type -> (message, accumulated weight)

    inputs = _decode_sorted(paths)
    for i, inp in enumerate(inputs):
        sessions.append(inp.session)
        stats.sources.append({"name": inp.path.name, **_session_summary(inp.session)})
        last_dist = None
        last_accum_power = None
        file_laps = 0
        file_splits = 0

        for rec in inp.records:
            if isinstance(rec, RawDefinitionRecord):
                parts.append(rec.source_bytes)
                continue
            gid = rec.definition.global_id

            if gid == SESSION:
                continue  # folded into the single rebuilt session
            if gid == ACTIVITY:
                if i == 0:
                    activity1 = project_data_record(rec, inp.registry).message
                continue
            if gid in (FILE_ID, FILE_CREATOR) and i > 0:
                continue

            if gid == TIME_IN_ZONE:
                # A time_in_zone message scoped to the session describes the whole
                # activity, so the source files' copies are dropped rather than
                # merged; lap-scoped ones survive with renumbered references.
                if idx.read(rec, F_TIZ_REFERENCE_MESG) == SESSION:
                    stats.dropped["session_time_in_zone"] += 1
                    continue
                if i > 0:
                    ri = idx.read(rec, F_TIZ_REFERENCE_INDEX)
                    if ri is not None:
                        rec = _patch(rec, idx, {F_TIZ_REFERENCE_INDEX: ri + lap_count}, inp.path)
            elif gid == LAP:
                rec = _patch(rec, idx, {F_MESSAGE_INDEX: lap_count + file_laps}, inp.path)
                file_laps += 1
            elif gid == SPLIT:
                if i > 0:
                    mi = idx.read(rec, F_MESSAGE_INDEX)
                    if mi is not None:
                        rec = _patch(rec, idx, {F_MESSAGE_INDEX: mi + split_count}, inp.path)
                file_splits += 1
            elif gid == SPLIT_SUMMARY:
                message = project_data_record(rec, inp.registry).message
                st = fval(message, "split_type")
                w_new = fval(message, "total_timer_time") or 1.0
                if st is not None and st in split_summaries:
                    existing, w_acc = split_summaries[st]
                    merge_summary(existing, message, w_acc, w_new)
                    split_summaries[st] = (existing, w_acc + w_new)
                    continue  # folded into the earlier message; drop this one
                if st is not None:
                    split_summaries[st] = (message, w_new)
                parts.append(_Pending(rec.header.source_bytes, message))
                continue
            elif gid == RECORD:
                stats.records += 1
                updates = {}
                d = idx.read(rec, F_RECORD_DISTANCE)
                if d is not None:
                    if i > 0:
                        d += dist_offset
                        updates[F_RECORD_DISTANCE] = d
                    last_dist = d
                ap = idx.read(rec, F_RECORD_ACCUMULATED_POWER)
                if ap is not None:
                    if i > 0 and accum_power_offset is not None:
                        ap += accum_power_offset
                        updates[F_RECORD_ACCUMULATED_POWER] = ap
                    last_accum_power = ap
                p = idx.read(rec, F_RECORD_POWER)
                if p is not None:
                    powers.append(p)
                if updates:
                    rec = _patch(rec, idx, updates, inp.path)

            parts.append(rec.source_bytes)

        if last_dist is None:
            raise MergeError(f"{inp.path}: no distance data in record messages")
        log.info(
            "merged %s: %d laps, %d splits, distance now %.2f km",
            inp.path.name,
            file_laps,
            file_splits,
            last_dist / (DISTANCE_SCALE * 1000),
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
    total_timer = fval(merged_session, "total_timer_time")
    tail = _encode_tail([merged_session, rebuild_activity(activity1, end_ms, total_timer)])

    log.info("encoding %d messages -> %s", len(parts) + 2, out)
    _write(out, inputs[0].header, parts, tail)
    log.info("wrote %s (%.1f MB)", out, out.stat().st_size / 1e6)

    stats.merged = {"name": "merged", **_session_summary(merged_session)}
    stats.laps = lap_count
    stats.splits = split_count
    stats.total_distance = fval(merged_session, "total_distance")
    stats.total_timer_time = total_timer
    stats.total_elapsed_time = fval(merged_session, "total_elapsed_time")
    stats.normalized_power = fval(merged_session, "normalized_power")
    return stats


def _write(out: Path, header: RawFileHeader, parts: list, tail: bytes) -> None:
    """Emit the merged stream under file 1's header, with fresh sizes and CRCs."""
    blob = b"".join(p if isinstance(p, bytes) else p.to_bytes() for p in parts) + tail
    body = rewrite_header_source_bytes(header, len(blob)) + blob
    out.write_bytes(body + struct.pack("<H", crc16(body)))


def _patch(rec: RawDataRecord, idx: PayloadIndex, updates: dict, path: Path) -> RawDataRecord:
    try:
        return idx.patch(rec, updates)
    except RawPatchError as e:
        raise MergeError(f"{path}: cannot rewrite merged value: {e}") from e
