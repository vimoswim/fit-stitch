"""Export a FIT activity as TCX (Training Center XML) with power extensions."""

import datetime
from pathlib import Path

from garmin_fit_sdk import Decoder, Stream

SEMICIRCLE_TO_DEG = 180.0 / 2**31
HR_SENTINEL = 255
POWER_SENTINEL = 65535

SPORT_MAP = {
    "cycling": "Biking",
    "running": "Running",
}

_HEADER = (
    '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
    '<TrainingCenterDatabase xsi:schemaLocation="http://www.garmin.com/xmlschemas/'
    'TrainingCenterDatabase/v2 http://www.garmin.com/xmlschemas/TrainingCenterDatabasev2.xsd" '
    'xmlns:ns3="http://www.garmin.com/xmlschemas/ActivityExtension/v2" '
    'xmlns="http://www.garmin.com/xmlschemas/TrainingCenterDatabase/v2" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
)


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _creator_block(file_id: dict | None) -> str:
    if not file_id:
        return ""
    name = str(file_id.get("garmin_product") or file_id.get("manufacturer") or "Unknown")
    unit_id = file_id.get("serial_number") or 0
    product = file_id.get("product") or 0
    return (
        f'      <Creator xsi:type="Device_t"><Name>{name}</Name><UnitId>{unit_id}</UnitId>'
        f"<ProductID>{product}</ProductID><Version><VersionMajor>0</VersionMajor>"
        "<VersionMinor>0</VersionMinor><BuildMajor>0</BuildMajor><BuildMinor>0</BuildMinor>"
        "</Version></Creator>\n"
    )


def export_tcx(fit_path: Path, tcx_path: Path) -> int:
    """Write a TCX rendering of ``fit_path``. Returns the trackpoint count."""
    messages, errors = Decoder(Stream.from_file(str(fit_path))).read()
    if errors:
        raise ValueError(f"cannot decode {fit_path}: {errors}")
    recs = messages.get("record_mesgs", [])
    sessions = messages.get("session_mesgs", [])
    if not recs or not sessions:
        raise ValueError(f"{fit_path}: not an activity file (no records/session)")
    s = sessions[0]
    file_ids = messages.get("file_id_mesgs", [])
    sport = SPORT_MAP.get(str(s.get("sport")), "Other")

    parts = [_HEADER, "  <Activities>\n", f'    <Activity Sport="{sport}">\n']
    parts.append(f"      <Id>{_iso(s['start_time'])}</Id>\n")
    parts.append(f'      <Lap StartTime="{_iso(s["start_time"])}">\n')
    parts.append(f"        <TotalTimeSeconds>{s['total_timer_time']}</TotalTimeSeconds>\n")
    parts.append(f"        <DistanceMeters>{s['total_distance']}</DistanceMeters>\n")
    if s.get("enhanced_max_speed") is not None:
        parts.append(f"        <MaximumSpeed>{s['enhanced_max_speed']}</MaximumSpeed>\n")
    parts.append(f"        <Calories>{s.get('total_calories') or 0}</Calories>\n")
    if s.get("avg_heart_rate") is not None:
        parts.append(
            f"        <AverageHeartRateBpm><Value>{s['avg_heart_rate']}</Value>"
            "</AverageHeartRateBpm>\n"
        )
    if s.get("max_heart_rate") is not None:
        parts.append(
            f"        <MaximumHeartRateBpm><Value>{s['max_heart_rate']}</Value>"
            "</MaximumHeartRateBpm>\n"
        )
    parts.append("        <Intensity>Active</Intensity>\n")
    if s.get("avg_cadence") is not None:
        parts.append(f"        <Cadence>{s['avg_cadence']}</Cadence>\n")
    parts.append("        <TriggerMethod>Manual</TriggerMethod>\n        <Track>\n")

    n_pts = 0
    for r in recs:
        ts = r.get("timestamp")
        if ts is None:
            continue
        tp = [f"          <Trackpoint>\n            <Time>{_iso(ts)}</Time>\n"]
        lat, lon = r.get("position_lat"), r.get("position_long")
        if lat is not None and lon is not None:
            tp.append(
                "            <Position>"
                f"<LatitudeDegrees>{lat * SEMICIRCLE_TO_DEG:.7f}</LatitudeDegrees>"
                f"<LongitudeDegrees>{lon * SEMICIRCLE_TO_DEG:.7f}</LongitudeDegrees>"
                "</Position>\n"
            )
        alt = r.get("enhanced_altitude", r.get("altitude"))
        if alt is not None:
            tp.append(f"            <AltitudeMeters>{alt}</AltitudeMeters>\n")
        if r.get("distance") is not None:
            tp.append(f"            <DistanceMeters>{r['distance']}</DistanceMeters>\n")
        hr = r.get("heart_rate")
        if hr is not None and hr != HR_SENTINEL:
            tp.append(f"            <HeartRateBpm><Value>{hr}</Value></HeartRateBpm>\n")
        cad = r.get("cadence")
        if cad is not None and cad != HR_SENTINEL:
            tp.append(f"            <Cadence>{cad}</Cadence>\n")
        spd = r.get("enhanced_speed", r.get("speed"))
        pwr = r.get("power")
        has_power = pwr is not None and pwr != POWER_SENTINEL
        if spd is not None or has_power:
            tp.append("            <Extensions><ns3:TPX>")
            if spd is not None:
                tp.append(f"<ns3:Speed>{spd}</ns3:Speed>")
            if has_power:
                tp.append(f"<ns3:Watts>{pwr}</ns3:Watts>")
            tp.append("</ns3:TPX></Extensions>\n")
        tp.append("          </Trackpoint>\n")
        parts.append("".join(tp))
        n_pts += 1

    parts.append("        </Track>\n        <Extensions><ns3:LX>")
    if s.get("enhanced_avg_speed") is not None:
        parts.append(f"<ns3:AvgSpeed>{s['enhanced_avg_speed']}</ns3:AvgSpeed>")
    if s.get("max_cadence") is not None:
        parts.append(f"<ns3:MaxBikeCadence>{s['max_cadence']}</ns3:MaxBikeCadence>")
    if s.get("avg_power") is not None:
        parts.append(f"<ns3:AvgWatts>{s['avg_power']}</ns3:AvgWatts>")
    if s.get("max_power") is not None:
        parts.append(f"<ns3:MaxWatts>{s['max_power']}</ns3:MaxWatts>")
    parts.append("</ns3:LX></Extensions>\n      </Lap>\n")
    parts.append(_creator_block(file_ids[0] if file_ids else None))
    parts.append("    </Activity>\n  </Activities>\n</TrainingCenterDatabase>\n")

    tcx_path.write_text("".join(parts), encoding="utf-8")
    return n_pts
