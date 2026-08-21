"""Direct payload access for wire records — the fast path for large activities.

Projecting a FIT record into typed ``Field`` objects costs ~84 allocations per
record, which dominates merge time on multi-hour activities (20 s and ~800 MB
for one 20 000-record file). The merge only ever reads or rewrites a handful of
numeric fields per record, so this module reads and patches those directly in
the record's payload bytes and leaves every other byte untouched.

Values here are **raw**: as stored on the wire, without the profile's
scale/offset applied. That is deliberate. The merge only ever adds an offset
taken from the same field of another record, so staying in raw units is exact
(no float round-trip through metres) and needs no profile lookup. For example
``distance`` is a uint32 of centimetres; adding two raw values is identical to
adding two metre values and re-scaling, minus the rounding.

Reads and writes address a field's first element, matching what ``fval`` and
``fset`` do on the projected path. Strings and unknown base types report as
absent, which makes callers leave the field alone.
"""

import struct
from dataclasses import replace

from fit_tool.base_type import BaseType
from fit_tool.wire.model import RawDataRecord, RawDefinitionRecord


class RawPatchError(Exception):
    """A field could not be rewritten in place (out of range for its base type)."""


def _layout(defn: RawDefinitionRecord) -> dict[int, tuple[int, BaseType]]:
    """Map field_id -> (payload offset, base type) for addressable fields.

    A field declared wider than its base type is an array; its first element
    sits at the field's offset, which is the element the projected path reads
    and writes too.
    """
    layout = {}
    offset = 0
    for fd in defn.field_definitions:
        try:
            base = BaseType(fd.base_type)
        except ValueError:
            base = None  # reserved/unknown base type: skip it, but still advance
        if base is not None and not base.is_string() and base.size and fd.size % base.size == 0:
            layout[fd.field_id] = (offset, base)
        offset += fd.size
    return layout


class PayloadIndex:
    """Field-layout cache, keyed by definition snapshot.

    The wire decoder attaches one shared ``RawDefinitionRecord`` object to every
    data record that uses it, so this holds one entry per definition rather than
    per record. The definition is kept as the value to pin it in memory for as
    long as the cache lives, which makes the ``id()`` key safe against reuse.
    """

    def __init__(self):
        self._cache: dict[int, tuple[RawDefinitionRecord, dict]] = {}

    def layout(self, defn: RawDefinitionRecord) -> dict[int, tuple[int, BaseType]]:
        entry = self._cache.get(id(defn))
        if entry is None:
            entry = (defn, _layout(defn))
            self._cache[id(defn)] = entry
        return entry[1]

    def read(self, rec: RawDataRecord, field_id: int):
        """Raw value of a field's first element, or None when it is absent."""
        slot = self.layout(rec.definition).get(field_id)
        if slot is None:
            return None
        offset, base = slot
        fmt = _endian(rec.definition) + base.struct_format
        try:
            return struct.unpack_from(fmt, rec.payload, offset)[0]
        except struct.error:
            return None

    def patch(self, rec: RawDataRecord, updates: dict[int, int]) -> RawDataRecord:
        """Rewrite raw field values in place, returning the updated record.

        Fields absent from the definition are ignored, matching ``fset``'s
        "not populated in this message" behaviour on the projected path.
        """
        layout = self.layout(rec.definition)
        slots = [(layout[fid], v) for fid, v in updates.items() if fid in layout]
        if not slots:
            return rec

        payload = bytearray(rec.payload)
        endian = _endian(rec.definition)
        for (offset, base), value in slots:
            if not base.is_valid(value) or value == base.invalid_raw_value():
                raise RawPatchError(
                    f"value {value} does not fit {base.name} "
                    f"(valid range {base.min}..{base.max - 1})"
                )
            struct.pack_into(endian + base.struct_format, payload, offset, value)

        data = bytes(payload)
        return replace(rec, payload=data, source_bytes=rec.header.source_bytes + data, dirty=True)


def _endian(defn: RawDefinitionRecord) -> str:
    return "<" if defn.architecture == 0 else ">"
