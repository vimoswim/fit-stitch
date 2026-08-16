"""validate_fit pass/fail behavior."""

import datetime

from fit_tool.fit_file import FitFile
from fit_tool.fit_file_builder import FitFileBuilder

from fit_stitch.merge import merge_files
from fit_stitch.validate import validate_fit
from tests.conftest import make_activity


def failed_checks(report):
    return [name for name, passed, _ in report.checks if not passed]


def test_valid_merged_file(two_rides, tmp_path):
    out = tmp_path / "merged.fit"
    merge_files(two_rides, out)
    report = validate_fit(out, expected_sources=two_rides)
    assert report.ok, failed_checks(report)
    assert report.stats["records"] == 120
    assert report.stats["total_distance_m"] == 960.0


def test_valid_single_fixture(tmp_path):
    path = make_activity(
        tmp_path / "ride.fit",
        start=datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC),
    )
    report = validate_fit(path)
    assert report.ok, failed_checks(report)


def test_truncated_file_fails(two_rides, tmp_path):
    out = tmp_path / "merged.fit"
    merge_files(two_rides, out)
    bad = tmp_path / "truncated.fit"
    bad.write_bytes(out.read_bytes()[:-50])
    report = validate_fit(bad)
    assert not report.ok
    assert "crc_integrity" in failed_checks(report)


def test_two_sessions_fail(tmp_path):
    src = make_activity(
        tmp_path / "ride.fit",
        start=datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC),
    )
    builder = FitFileBuilder(auto_define=True)
    session_msg = None
    for rec in FitFile.from_file(str(src)).records:
        builder.add(rec.message)
        if getattr(rec.message, "global_id", None) == 18:
            session_msg = rec.message
    builder.add(session_msg)  # duplicate the session
    bad = tmp_path / "twosessions.fit"
    builder.build().to_file(str(bad))
    report = validate_fit(bad)
    assert "one_session" in failed_checks(report)
