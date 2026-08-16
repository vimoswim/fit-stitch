"""Unit tests for Normalized Power and derived metrics."""

import datetime

import pytest
from garmin_fit_sdk import Decoder, Stream

from fit_stitch.merge import merge_files
from fit_stitch.session import compute_normalized_power
from tests.conftest import make_activity


def reference_np(powers: list[int]) -> float:
    """Naive independent implementation for cross-checking."""
    rolling = [sum(powers[i - 30 : i]) / 30.0 for i in range(30, len(powers) + 1)]
    return (sum(r**4 for r in rolling) / len(rolling)) ** 0.25


def test_np_constant_power():
    assert compute_normalized_power([200] * 120) == 200


def test_np_too_short():
    assert compute_normalized_power([200] * 30) is None
    assert compute_normalized_power([]) is None


def test_np_step_profile_matches_reference():
    powers = [100] * 60 + [300] * 60
    assert compute_normalized_power(powers) == round(reference_np(powers))


def test_np_higher_than_average_for_variable_power():
    powers = [0] * 60 + [400] * 60
    np_val = compute_normalized_power(powers)
    assert np_val > 200  # NP must exceed the plain 200 W average


def test_if_and_tss_written(two_rides, tmp_path):
    out = tmp_path / "merged.fit"
    merge_files(two_rides, out)
    messages, _ = Decoder(Stream.from_file(str(out))).read()
    s = messages["session_mesgs"][0]
    # 200 W and 100 W for 60 s each: NP is defined and IF = NP / 250 (fixture FTP)
    np_val = s["normalized_power"]
    assert np_val is not None
    assert s["intensity_factor"] == pytest.approx(np_val / 250, abs=0.001)
    expected_tss = 120.0 * np_val * (np_val / 250) / (250 * 3600.0) * 100
    assert s["training_stress_score"] == pytest.approx(expected_tss, abs=0.1)


def test_np_excludes_sentinels(tmp_path):
    t0 = datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC)
    a = make_activity(tmp_path / "a.fit", start=t0, power=200)
    b = make_activity(
        tmp_path / "b.fit",
        start=t0 + datetime.timedelta(minutes=6),
        power=lambda t: 0xFFFF if t % 2 else 200,
    )
    out = tmp_path / "merged.fit"
    merge_files([a, b], out)
    messages, _ = Decoder(Stream.from_file(str(out))).read()
    # sentinel samples are excluded, so NP stays at the constant 200 W
    assert messages["session_mesgs"][0]["normalized_power"] == 200
