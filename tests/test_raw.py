"""Raw payload access must agree with fit-tool's projected field access.

The merge's fast path rewrites fields directly in a record's payload instead of
projecting it into typed ``Field`` objects. These tests pin that shortcut to the
slow path it replaces: same values read, same bytes written.
"""

import datetime

import pytest
from fit_tool.compatibility import project_data_record
from fit_tool.wire import WireDecoder
from fit_tool.wire.model import RawDataRecord

from fit_stitch.constants import (
    F_RECORD_ACCUMULATED_POWER,
    F_RECORD_DISTANCE,
    F_RECORD_POWER,
    RECORD,
)
from fit_stitch.raw import PayloadIndex, RawPatchError
from tests.conftest import make_activity

DISTANCE_SCALE = 100
UNUSED_FIELD_ID = 200  # not present in the fixture's record definition


@pytest.fixture
def records(tmp_path):
    """Raw record-message wire records from a short synthetic activity."""
    path = make_activity(
        tmp_path / "ride.fit",
        start=datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC),
        duration_s=30,
    )
    document = WireDecoder().decode(path.read_bytes())
    return [
        r
        for segment in document.segments
        for r in segment.records
        if isinstance(r, RawDataRecord) and r.definition.global_id == RECORD
    ]


def projected(rec, name):
    return project_data_record(rec, {}).message.get_field_by_name(name).get_value()


def test_read_matches_projected_values(records):
    idx = PayloadIndex()
    assert len(records) == 30
    for rec in records:
        # distance is stored as centimetres; raw access deliberately skips the scale
        assert idx.read(rec, F_RECORD_DISTANCE) == round(
            projected(rec, "distance") * DISTANCE_SCALE
        )
        assert idx.read(rec, F_RECORD_POWER) == projected(rec, "power")
        assert idx.read(rec, F_RECORD_ACCUMULATED_POWER) == projected(rec, "accumulated_power")


def test_patch_writes_the_same_bytes_as_a_projected_write(records):
    idx = PayloadIndex()
    rec = records[0]
    offset_m = 1234.56

    patched = idx.patch(
        rec,
        {F_RECORD_DISTANCE: idx.read(rec, F_RECORD_DISTANCE) + round(offset_m * DISTANCE_SCALE)},
    )

    message = project_data_record(rec, {}).message
    f = message.get_field_by_name("distance")
    f.set_value(0, f.get_value() + offset_m)

    assert patched.payload == message.to_bytes()
    assert patched.source_bytes == patched.header.source_bytes + patched.payload
    assert len(patched.source_bytes) == len(rec.source_bytes)
    assert patched.dirty


def test_patch_leaves_the_original_record_untouched(records):
    idx = PayloadIndex()
    rec = records[0]
    before = rec.payload

    idx.patch(rec, {F_RECORD_DISTANCE: 999})

    assert rec.payload == before


def test_absent_field_reads_as_none_and_patches_as_a_no_op(records):
    idx = PayloadIndex()
    rec = records[0]

    assert idx.read(rec, UNUSED_FIELD_ID) is None
    assert idx.patch(rec, {UNUSED_FIELD_ID: 1}) is rec


def test_value_too_large_for_the_base_type_is_rejected(records):
    idx = PayloadIndex()
    with pytest.raises(RawPatchError):
        idx.patch(records[0], {F_RECORD_DISTANCE: 2**32})


def test_the_invalid_sentinel_is_rejected_as_a_written_value(records):
    """Writing a field's invalid marker would silently erase it."""
    idx = PayloadIndex()
    with pytest.raises(RawPatchError):
        idx.patch(records[0], {F_RECORD_DISTANCE: 0xFFFFFFFF})


def test_layout_is_cached_per_definition(records):
    idx = PayloadIndex()
    first = idx.layout(records[0].definition)
    assert idx.layout(records[-1].definition) is first
    assert len(idx._cache) == 1
