"""Synthetic FIT activity factory for tests.

All FIT files used in tests are generated here with fabricated data (invented
GPS grid near lat 50.0 / lon 19.9, constant or callable power profiles). Real
activity files must never be added to the repo — they contain personal GPS and
health data.
"""

import datetime
from collections.abc import Callable
from pathlib import Path

import pytest
from fit_tool.fit_file_builder import FitFileBuilder
from fit_tool.profile.messages.activity_message import ActivityMessage
from fit_tool.profile.messages.event_message import EventMessage
from fit_tool.profile.messages.file_id_message import FileIdMessage
from fit_tool.profile.messages.lap_message import LapMessage
from fit_tool.profile.messages.record_message import RecordMessage
from fit_tool.profile.messages.session_message import SessionMessage
from fit_tool.profile.profile_type import Event, EventType, FileType, Manufacturer, Sport

FIT_EPOCH_S = 631065600  # 1989-12-31T00:00:00Z in Unix seconds
TZ_OFFSET_S = 7200  # fixture timezone: UTC+2
HR_SENTINEL = 0xFF

# fit-tool position properties take degrees and scale to semicircles internally
BASE_LAT_DEG = 50.0
BASE_LON_DEG = 19.9


def make_activity(
    path: Path,
    *,
    start: datetime.datetime,
    duration_s: int = 60,
    power: int | Callable[[int], int] = 200,
    hr: int = 140,
    cadence: int = 85,
    speed: float = 8.0,
    n_laps: int = 1,
    hr_sentinel: bool = False,
    with_accumulated_power: bool = True,
    sport: int = Sport.CYCLING.value,
) -> Path:
    """Write a minimal but well-formed FIT activity file and return its path."""
    start_ms = round(start.timestamp() * 1000)
    end_ms = start_ms + duration_s * 1000
    power_at = power if callable(power) else (lambda _t: power)
    powers = [power_at(t) for t in range(duration_s)]

    builder = FitFileBuilder(auto_define=True, min_string_size=0)

    fid = FileIdMessage()
    fid.type = FileType.ACTIVITY.value
    fid.manufacturer = Manufacturer.DEVELOPMENT.value
    fid.product = 1234
    fid.serial_number = 987654321
    fid.time_created = start_ms
    builder.add(fid)

    ev = EventMessage()
    ev.timestamp = start_ms
    ev.event = Event.TIMER.value
    ev.event_type = EventType.START.value
    builder.add(ev)

    accum = 0
    for t in range(duration_s):
        r = RecordMessage()
        r.timestamp = start_ms + t * 1000
        r.position_lat = BASE_LAT_DEG + t * 1e-5
        r.position_long = BASE_LON_DEG + t * 1e-5
        r.distance = speed * (t + 1)
        r.enhanced_speed = speed
        r.enhanced_altitude = 200.0
        r.power = powers[t]
        r.heart_rate = HR_SENTINEL if hr_sentinel else hr
        r.cadence = cadence
        if with_accumulated_power:
            accum += powers[t]
            r.accumulated_power = accum
        builder.add(r)

    ev2 = EventMessage()
    ev2.timestamp = end_ms
    ev2.event = Event.TIMER.value
    ev2.event_type = EventType.STOP_ALL.value
    builder.add(ev2)

    lap_len = duration_s // n_laps
    for i in range(n_laps):
        lap = LapMessage()
        lap.message_index = i
        lap.start_time = start_ms + i * lap_len * 1000
        lap.timestamp = start_ms + (i + 1) * lap_len * 1000
        lap.total_elapsed_time = float(lap_len)
        lap.total_timer_time = float(lap_len)
        lap.total_distance = speed * lap_len
        builder.add(lap)

    valid_powers = [p for p in powers if p != 0xFFFF] or [0]
    avg_power = round(sum(valid_powers) / len(valid_powers))
    s = SessionMessage()
    s.message_index = 0
    s.timestamp = end_ms
    s.start_time = start_ms
    s.sport = sport
    s.total_elapsed_time = float(duration_s)
    s.total_timer_time = float(duration_s)
    s.total_distance = speed * duration_s
    s.enhanced_avg_speed = speed
    s.enhanced_max_speed = speed
    s.avg_power = avg_power
    s.max_power = max(valid_powers)
    s.avg_heart_rate = HR_SENTINEL if hr_sentinel else hr
    s.max_heart_rate = HR_SENTINEL if hr_sentinel else hr + 15
    s.avg_cadence = cadence
    s.max_cadence = cadence + 10
    s.threshold_power = 250
    # power-meter devices write these; the merge recomputes them in place
    s.normalized_power = avg_power
    s.intensity_factor = avg_power / 250
    s.training_stress_score = 1.0
    s.first_lap_index = 0
    s.num_laps = n_laps
    builder.add(s)

    a = ActivityMessage()
    a.timestamp = end_ms
    a.local_timestamp = round(end_ms / 1000) - FIT_EPOCH_S + TZ_OFFSET_S
    a.total_timer_time = float(duration_s)
    a.num_sessions = 1
    builder.add(a)

    builder.build().to_file(str(path))
    return path


@pytest.fixture
def two_rides(tmp_path):
    """Two 60 s activities, 5 minutes apart: 200 W then 100 W."""
    t0 = datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC)
    a = make_activity(tmp_path / "a.fit", start=t0, power=200)
    b = make_activity(tmp_path / "b.fit", start=t0 + datetime.timedelta(minutes=6), power=100)
    return [a, b]


@pytest.fixture
def three_rides(tmp_path):
    """Three 60 s activities with gaps, at 200/100/300 W."""
    t0 = datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC)
    return [
        make_activity(tmp_path / "a.fit", start=t0, power=200),
        make_activity(tmp_path / "b.fit", start=t0 + datetime.timedelta(minutes=6), power=100),
        make_activity(tmp_path / "c.fit", start=t0 + datetime.timedelta(minutes=12), power=300),
    ]
