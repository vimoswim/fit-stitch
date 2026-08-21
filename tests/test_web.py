"""The in-memory API the browser build calls.

These pin the contract the JavaScript side depends on: bytes in, bytes out, a
report that survives json.dumps, failures as data rather than exceptions, and
no scratch files left behind holding someone's GPS trace.
"""

import json
import logging

from fit_stitch.web import merge_bytes, validate_bytes

FIT_HEADER_MAGIC = b".FIT"
BINARY_KEYS = ("output", "tcx")


def as_pairs(paths):
    return [(p.name, p.read_bytes()) for p in paths]


def test_merge_returns_a_valid_fit_file(two_rides):
    result = merge_bytes(as_pairs(two_rides))

    assert result["ok"]
    assert result["error"] is None
    assert result["output_name"] == "merged.fit"
    assert result["output"][8:12] == FIT_HEADER_MAGIC
    assert result["summary"]["records"] == 120
    assert result["validation"]["ok"]
    assert all(c["passed"] for c in result["validation"]["checks"])


def test_report_survives_json_serialization(two_rides):
    """The decoder hands back datetimes; the page can only take JSON."""
    result = merge_bytes(as_pairs(two_rides))
    payload = {k: v for k, v in result.items() if k not in BINARY_KEYS}

    round_tripped = json.loads(json.dumps(payload))

    assert round_tripped["validation"]["stats"]["start_time"].startswith("20")
    assert round_tripped["comparison"]["columns"] == ["a.fit", "b.fit", "merged"]


def test_comparison_carries_preformatted_cells(two_rides):
    table = merge_bytes(as_pairs(two_rides))["comparison"]

    distance = next(r for r in table["rows"] if r["label"] == "distance")
    assert distance["values"] == ["0.48 km", "0.48 km", "0.96 km"]


def test_tcx_export_is_optional(two_rides):
    without = merge_bytes(as_pairs(two_rides))
    assert without["tcx"] is None and without["tcx_name"] is None

    with_tcx = merge_bytes(as_pairs(two_rides), tcx=True)
    assert with_tcx["tcx_name"] == "merged.tcx"
    assert b"TrainingCenterDatabase" in with_tcx["tcx"]


def test_unmergeable_inputs_come_back_as_a_message(two_rides):
    """Overlapping activities are a user error, not a crash."""
    same_file = [(two_rides[0].name, two_rides[0].read_bytes())] * 2

    result = merge_bytes(same_file)

    assert result["ok"] is False
    assert "overlap" in result["error"]


def test_a_single_file_is_rejected(two_rides):
    result = merge_bytes(as_pairs(two_rides[:1]))
    assert result["ok"] is False
    assert "at least 2" in result["error"]


def test_identically_named_inputs_keep_their_own_column(two_rides):
    files = [("ride.fit", p.read_bytes()) for p in two_rides]

    result = merge_bytes(files)

    assert result["ok"]
    assert result["comparison"]["columns"] == ["ride.fit", "ride.fit", "merged"]


def test_path_components_in_a_name_are_stripped(two_rides):
    files = [("../../etc/a.fit", two_rides[0].read_bytes()), ("b.fit", two_rides[1].read_bytes())]

    result = merge_bytes(files)

    assert result["ok"]
    assert result["comparison"]["columns"] == ["a.fit", "b.fit", "merged"]


def test_progress_lines_reach_the_callback_and_the_handler_is_removed(two_rides):
    lines = []
    before = len(logging.getLogger("fit_stitch").handlers)

    merge_bytes(as_pairs(two_rides), on_progress=lines.append)

    assert any("decoding" in line for line in lines)
    assert any("rebuilding" in line for line in lines)
    assert len(logging.getLogger("fit_stitch").handlers) == before


def test_a_broken_progress_callback_does_not_break_the_merge(two_rides):
    def explode(_line):
        raise RuntimeError("UI is on fire")

    result = merge_bytes(as_pairs(two_rides), on_progress=explode)

    assert result["ok"]


def test_validate_accepts_a_single_file(two_rides):
    name, data = two_rides[0].name, two_rides[0].read_bytes()

    report = validate_bytes(name, data)

    assert report["ok"]
    assert report["name"] == name
    assert [c["name"] for c in report["checks"]][:2] == ["is_fit", "crc_integrity"]
    json.dumps(report)


def test_validate_reports_a_corrupt_file_instead_of_raising():
    report = validate_bytes("junk.fit", b"not a fit file at all")

    assert report["ok"] is False
    assert not report["checks"][0]["passed"]
