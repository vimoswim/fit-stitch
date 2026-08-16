"""CLI behavior and exit codes (invoked in-process)."""

from fit_stitch.cli import EXIT_ERROR, EXIT_OK, EXIT_VALIDATION_FAILED, main
from fit_stitch.merge import merge_files


def test_merge_command(two_rides, tmp_path, capsys):
    out = tmp_path / "merged.fit"
    code = main([str(two_rides[0]), str(two_rides[1]), "-o", str(out)])
    assert code == EXIT_OK
    assert out.is_file()
    captured = capsys.readouterr().out
    assert "0.96 km" in captured
    assert "✗" not in captured


def test_merge_with_tcx(two_rides, tmp_path):
    out = tmp_path / "merged.fit"
    code = main([str(two_rides[0]), str(two_rides[1]), "-o", str(out), "--tcx"])
    assert code == EXIT_OK
    assert out.with_suffix(".tcx").is_file()


def test_single_input_is_usage_error(two_rides, tmp_path):
    code = main([str(two_rides[0]), "-o", str(tmp_path / "out.fit")])
    assert code == EXIT_ERROR


def test_missing_input_is_error(tmp_path):
    code = main(
        [str(tmp_path / "nope1.fit"), str(tmp_path / "nope2.fit"), "-o", str(tmp_path / "out.fit")]
    )
    assert code == EXIT_ERROR


def test_validate_command(two_rides, tmp_path):
    out = tmp_path / "merged.fit"
    merge_files(two_rides, out)
    assert main(["validate", str(out)]) == EXIT_OK

    bad = tmp_path / "bad.fit"
    bad.write_bytes(out.read_bytes()[:-50])
    assert main(["validate", str(bad)]) == EXIT_VALIDATION_FAILED

    assert main(["validate", str(tmp_path / "missing.fit")]) == EXIT_ERROR
