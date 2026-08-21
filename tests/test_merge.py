"""Merge invariants, cross-checked with the official Garmin SDK decoder."""

import datetime

import pytest
from fit_tool.profile.profile_type import Sport
from fit_tool.wire import WireDecoder
from fit_tool.wire.model import RawDataRecord
from garmin_fit_sdk import Decoder, Stream

from fit_stitch.constants import RECORD
from fit_stitch.merge import MergeError, merge_files
from tests.conftest import FIT_EPOCH_S, TZ_OFFSET_S, make_activity


def decode(path):
    messages, errors = Decoder(Stream.from_file(str(path))).read()
    assert not errors
    return messages


def check_integrity(path):
    return Decoder(Stream.from_file(str(path))).check_integrity()


def test_two_file_merge(two_rides, tmp_path):
    out = tmp_path / "merged.fit"
    stats = merge_files(two_rides, out)
    assert check_integrity(out)
    m = decode(out)

    assert len(m["session_mesgs"]) == 1
    assert len(m["activity_mesgs"]) == 1
    assert len(m["file_id_mesgs"]) == 1
    recs = m["record_mesgs"]
    assert len(recs) == 120 == stats.records

    ts = [r["timestamp"] for r in recs]
    assert ts == sorted(ts)
    dists = [r["distance"] for r in recs]
    assert dists == sorted(dists)
    assert dists[-1] == pytest.approx(2 * 8.0 * 60)

    s = m["session_mesgs"][0]
    assert s["total_timer_time"] == pytest.approx(120.0)
    assert s["total_distance"] == pytest.approx(960.0)
    # elapsed spans the 5-minute gap: 6 min offset + 60 s second ride
    assert s["total_elapsed_time"] == pytest.approx(360.0 + 60.0)
    # time-weighted average of 200 W (60 s) and 100 W (60 s)
    assert s["avg_power"] == 150
    assert s["max_power"] == 200
    assert s["max_heart_rate"] == 155

    accum = [r["accumulated_power"] for r in recs if r.get("accumulated_power") is not None]
    assert accum == sorted(accum)
    assert accum[-1] == 200 * 60 + 100 * 60


def test_three_file_merge(three_rides, tmp_path):
    out = tmp_path / "merged3.fit"
    stats = merge_files(three_rides, out)
    assert check_integrity(out)
    m = decode(out)
    assert len(m["session_mesgs"]) == 1
    assert len(m["activity_mesgs"]) == 1
    assert stats.records == 180

    s = m["session_mesgs"][0]
    assert s["total_timer_time"] == pytest.approx(180.0)
    assert s["total_distance"] == pytest.approx(3 * 480.0)
    # fold-weighted mean of 200/100/300 over equal 60 s weights
    assert s["avg_power"] == 200

    laps = m["lap_mesgs"]
    assert [lap["message_index"] for lap in laps] == list(range(len(laps)))

    sess_start = s["start_time"]
    sess_end = sess_start + datetime.timedelta(seconds=s["total_elapsed_time"])
    for src in three_rides:
        sr = decode(src)["record_mesgs"]
        assert sess_start <= sr[0]["timestamp"]
        assert sr[-1]["timestamp"] <= sess_end


def test_input_order_does_not_matter(two_rides, tmp_path):
    out1 = tmp_path / "fwd.fit"
    out2 = tmp_path / "rev.fit"
    s1 = merge_files(two_rides, out1)
    s2 = merge_files(list(reversed(two_rides)), out2)
    assert s1.total_distance == s2.total_distance
    assert s1.total_timer_time == s2.total_timer_time
    assert s1.records == s2.records
    assert (
        decode(out2)["session_mesgs"][0]["start_time"]
        == (decode(out1)["session_mesgs"][0]["start_time"])
    )


def test_overlapping_inputs_rejected(tmp_path):
    t0 = datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC)
    a = make_activity(tmp_path / "a.fit", start=t0, duration_s=120)
    b = make_activity(tmp_path / "b.fit", start=t0 + datetime.timedelta(seconds=60))
    with pytest.raises(MergeError, match="overlap"):
        merge_files([a, b], tmp_path / "out.fit")


def test_single_input_rejected(two_rides, tmp_path):
    with pytest.raises(MergeError, match="at least 2"):
        merge_files(two_rides[:1], tmp_path / "out.fit")


def test_mismatched_sports_rejected(tmp_path):
    t0 = datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC)
    a = make_activity(tmp_path / "ride.fit", start=t0)
    b = make_activity(
        tmp_path / "run.fit",
        start=t0 + datetime.timedelta(minutes=6),
        sport=Sport.RUNNING.value,
    )
    with pytest.raises(MergeError, match="different activity types.*cycling.*running"):
        merge_files([a, b], tmp_path / "out.fit")


def test_stats_carry_source_and_merged_summaries(two_rides, tmp_path):
    stats = merge_files(two_rides, tmp_path / "merged.fit")
    assert [s["name"] for s in stats.sources] == ["a.fit", "b.fit"]
    assert all(s["sport"] == "cycling" for s in stats.sources)
    assert stats.sources[0]["avg_power"] == 200
    assert stats.sources[1]["avg_power"] == 100
    assert stats.sources[0]["distance_m"] == pytest.approx(480.0)
    assert stats.merged["name"] == "merged"
    assert stats.merged["distance_m"] == pytest.approx(960.0)
    assert stats.merged["timer_s"] == pytest.approx(120.0)
    assert stats.merged["avg_power"] == 150


def test_sentinel_hr_kept_from_first_file(tmp_path):
    t0 = datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC)
    a = make_activity(tmp_path / "a.fit", start=t0, hr=140)
    b = make_activity(
        tmp_path / "b.fit", start=t0 + datetime.timedelta(minutes=6), hr_sentinel=True
    )
    out = tmp_path / "merged.fit"
    merge_files([a, b], out)
    s = decode(out)["session_mesgs"][0]
    # file 2's avg HR is the 0xFF invalid sentinel: keep file 1's average
    assert s["avg_heart_rate"] == 140


def test_local_timestamp_keeps_timezone_offset(two_rides, tmp_path):
    out = tmp_path / "merged.fit"
    merge_files(two_rides, out)
    a = decode(out)["activity_mesgs"][0]
    end_fit_s = round(a["timestamp"].timestamp()) - FIT_EPOCH_S
    assert a["local_timestamp"] - end_fit_s == TZ_OFFSET_S


def test_first_file_records_survive_byte_for_byte(two_rides, tmp_path):
    """The merge copies untouched records verbatim rather than re-encoding them.

    File 1 needs no distance or power offset, so every one of its record
    messages must appear in the output exactly as it was read. This is what
    keeps undocumented Garmin messages intact: preservation is a property of
    the bytes, not of how well the profile happens to describe a message.
    """
    document = WireDecoder().decode(two_rides[0].read_bytes())
    source_records = [
        r
        for segment in document.segments
        for r in segment.records
        if isinstance(r, RawDataRecord) and r.definition.global_id == RECORD
    ]
    assert source_records

    out = tmp_path / "merged.fit"
    merge_files(two_rides, out)
    merged = out.read_bytes()

    run = b"".join(r.source_bytes for r in source_records)
    assert run in merged, "file 1's record stream was not copied verbatim"


def test_second_file_records_differ_only_in_the_offset_fields(two_rides, tmp_path):
    """File 2 is rewritten only where the merge says it should be."""
    document = WireDecoder().decode(two_rides[1].read_bytes())
    source_records = [
        r
        for segment in document.segments
        for r in segment.records
        if isinstance(r, RawDataRecord) and r.definition.global_id == RECORD
    ]

    out = tmp_path / "merged.fit"
    merge_files(two_rides, out)
    merged = out.read_bytes()

    # Same length, same header byte, but shifted distance/accumulated power, so
    # the original bytes must be gone while the record count stays the same.
    assert source_records[-1].source_bytes not in merged
    assert len(decode(out)["record_mesgs"]) == 120
