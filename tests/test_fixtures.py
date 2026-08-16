"""Pin fit-tool fixture encoding against the official Garmin SDK decoder."""

import datetime

from garmin_fit_sdk import Decoder, Stream

from tests.conftest import make_activity


def test_fixture_decodes_with_official_sdk(tmp_path):
    path = make_activity(
        tmp_path / "ride.fit",
        start=datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC),
        duration_s=60,
        n_laps=2,
    )
    stream = Stream.from_file(str(path))
    decoder = Decoder(stream)
    assert decoder.is_fit()
    stream.reset()
    assert Decoder(stream).check_integrity()
    stream.reset()
    messages, errors = Decoder(stream).read()
    assert not errors
    assert len(messages["record_mesgs"]) == 60
    assert len(messages["session_mesgs"]) == 1
    assert len(messages["activity_mesgs"]) == 1
    assert len(messages["lap_mesgs"]) == 2
    assert len(messages["file_id_mesgs"]) == 1

    recs = messages["record_mesgs"]
    assert recs[0]["power"] == 200
    assert recs[-1]["distance"] == 8.0 * 60
    s = messages["session_mesgs"][0]
    assert s["total_distance"] == 8.0 * 60
    assert s["total_timer_time"] == 60.0
