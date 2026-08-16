"""Safe field access and the generic summary-field combiner.

fit-tool quirks this module encodes:

- ``date_time`` fields are read/written as **milliseconds** since the Unix
  epoch, but ``local_date_time`` fields stay **raw seconds** since the FIT
  epoch. Callers doing timestamp arithmetic must not mix the two.
- Profile fields may exist on a message class without being populated in a
  given file; setting them raises ``FitEncodingError`` ("not growable"), which
  is treated as "skip".
- FIT invalid-value sentinels (255, 65535, ...) decode as ordinary integers;
  ``combine`` refuses to fold them into sums/averages/extrema.
"""

from fit_tool.exceptions import FitEncodingError

from fit_stitch.constants import (
    EXPLICIT_SUM,
    KEEP_FIRST,
    MAX_NOT_SUM,
    SENTINELS,
    SUM_EXCEPTIONS,
)


def fval(msg, name):
    """Return a field's (first) value, or None if absent/unreadable."""
    f = msg.get_field_by_name(name) if msg else None
    if f is None:
        return None
    try:
        return f.get_value()
    except (TypeError, ValueError, IndexError):
        return None


def fset(msg, name, value):
    """Set a field value (scalar or sequence). Returns False if not settable."""
    f = msg.get_field_by_name(name)
    if f is None or value is None:
        return False
    try:
        if isinstance(value, (list, tuple)):
            for i, v in enumerate(value):
                f.set_value(i, v)
        else:
            f.set_value(0, value)
    except FitEncodingError:
        return False  # field not populated in this message, or value out of range
    return True


def is_session_scoped_tiz(msg):
    """True for time_in_zone messages that reference the session message."""
    ref = fval(msg, "reference_mesg")
    return ref in (18, "18", "session")


def combine(v1, v2, w1, w2, rule):
    """Combine two field values by rule ('sum'/'max'/'min'/'avg').

    Returns None (meaning: keep the first value) when either side is missing
    or is a FIT invalid-value sentinel.
    """
    if v1 is None or v2 is None:
        return None
    if (isinstance(v1, int) and v1 in SENTINELS) or (isinstance(v2, int) and v2 in SENTINELS):
        return None
    if rule == "sum":
        r = v1 + v2
    elif rule == "max":
        r = max(v1, v2)
    elif rule == "min":
        r = min(v1, v2)
    else:  # time-weighted average
        r = (v1 * w1 + v2 * w2) / (w1 + w2)
    if isinstance(v1, int) and isinstance(v2, int):
        r = round(r)
    return r


def _rule_for(name: str) -> str | None:
    if name in MAX_NOT_SUM:
        return "max"
    if name in EXPLICIT_SUM or (name.startswith("total_") and name not in SUM_EXCEPTIONS):
        return "sum"
    if "max_" in name:
        return "max"
    if "min_" in name:
        return "min"
    if "avg_" in name or name == "left_right_balance":
        return "avg"
    return None  # unknown semantics: keep the first file's value


def merge_summary(m1, m2, w1, w2):
    """Fold m2's summary fields into m1 using name-based rules.

    w1/w2 weight the averages — pass each side's total_timer_time (for a fold,
    the accumulated timer time so far vs. the new file's timer time).
    """
    for f in list(m1.fields):
        name = getattr(f, "name", None)
        if not name or name in KEEP_FIRST:
            continue
        f2 = m2.get_field_by_name(name)
        if f2 is None:
            continue
        try:
            vs1, vs2 = f.get_values(), f2.get_values()
        except (TypeError, ValueError, IndexError):
            continue
        if vs1 is None or vs2 is None or len(vs1) != len(vs2):
            continue
        rule = _rule_for(name)
        if rule is None:
            continue
        for i, (v1, v2) in enumerate(zip(vs1, vs2)):
            r = combine(v1, v2, w1, w2, rule)
            if r is not None:
                try:
                    f.set_value(i, r)
                except FitEncodingError:
                    pass  # out of range (e.g. both inputs invalid sentinels): keep m1's value
