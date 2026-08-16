"""Normalized Power and single session/activity rebuild for the merged file."""

from fit_stitch.fields import combine, fset, fval, merge_summary

NP_WINDOW = 30  # samples; assumes 1 Hz recording
POWER_SENTINEL = 0xFFFF


def compute_normalized_power(powers: list[int]) -> int | None:
    """Normalized Power: 30-sample rolling average, mean of 4th powers, 4th root.

    Sentinel samples must be filtered out by the caller. Returns None when the
    stream is too short for a full window.
    """
    if len(powers) <= NP_WINDOW:
        return None
    win_sum = sum(powers[:NP_WINDOW])
    total4 = (win_sum / NP_WINDOW) ** 4
    n4 = 1
    for i in range(NP_WINDOW, len(powers)):
        win_sum += powers[i] - powers[i - NP_WINDOW]
        total4 += (win_sum / NP_WINDOW) ** 4
        n4 += 1
    return round((total4 / n4) ** 0.25)


def rebuild_session(sessions: list, powers: list[int], lap_count: int):
    """Fold all source sessions into sessions[0] and return (session, end_ms).

    Averages are folded with an accumulating weight (w_acc grows by each file's
    timer time), which keeps time-weighted means exact across N files.
    """
    base = sessions[0]
    w_acc = fval(base, "total_timer_time")
    total_timer = w_acc
    total_dist = fval(base, "total_distance")
    for s in sessions[1:]:
        w_i = fval(s, "total_timer_time")
        merge_summary(base, s, w_acc, w_i)
        w_acc += w_i
        total_timer += w_i
        total_dist += fval(s, "total_distance")

    last = sessions[-1]
    start_ms = fval(base, "start_time")
    # End of ride = last session's own start + elapsed (device-consistent math).
    end_ms = fval(last, "start_time") + round(fval(last, "total_elapsed_time") * 1000)

    avg_speed = total_dist / total_timer if total_timer else None
    fset(base, "timestamp", end_ms)
    fset(base, "total_elapsed_time", (end_ms - start_ms) / 1000.0)
    fset(base, "total_timer_time", total_timer)
    fset(base, "total_distance", total_dist)
    fset(base, "enhanced_avg_speed", avg_speed)
    fset(base, "avg_speed", avg_speed)
    fset(base, "num_laps", lap_count)
    fset(base, "first_lap_index", 0)
    fset(base, "end_position_lat", fval(last, "end_position_lat"))
    fset(base, "end_position_long", fval(last, "end_position_long"))

    # Bounding box: fold max/min across all sessions. Assumes the track does
    # not cross the antimeridian.
    for name, rule in (
        ("nec_lat", "max"),
        ("nec_long", "max"),
        ("swc_lat", "min"),
        ("swc_long", "min"),
    ):
        acc = fval(base, name)
        for s in sessions[1:]:
            acc = combine(acc, fval(s, name), 1, 1, rule) or acc
        fset(base, name, acc)

    # Left/right balance (left_right_balance_100): bit 15 = right-flag,
    # low bits = percent * 100. Weighted on the masked value, flag preserved.
    bal_num = 0.0
    bal_w = 0.0
    flag = None
    for s in sessions:
        b = fval(s, "left_right_balance")
        w = fval(s, "total_timer_time")
        if b is not None and w:
            if flag is None:
                flag = b & 0x8000
            bal_num += (b & 0x3FFF) * w
            bal_w += w
    if bal_w and flag is not None:
        fset(base, "left_right_balance", round(bal_num / bal_w) | flag)

    np_val = compute_normalized_power([p for p in powers if p != POWER_SENTINEL])
    ftp = fval(base, "threshold_power")
    if np_val is not None:
        fset(base, "normalized_power", np_val)
        if ftp:
            if_val = np_val / ftp
            fset(base, "intensity_factor", if_val)
            fset(
                base,
                "training_stress_score",
                round(total_timer * np_val * if_val / (ftp * 3600.0) * 100, 1),
            )
    return base, end_ms


def rebuild_activity(activity, end_ms: int, total_timer: float):
    """Point file 1's activity message at the merged ride's end."""
    act_ts = fval(activity, "timestamp")
    local_ts = fval(activity, "local_timestamp")
    fset(activity, "timestamp", end_ms)
    fset(activity, "total_timer_time", total_timer)
    fset(activity, "num_sessions", 1)
    if act_ts is not None and local_ts is not None:
        # timestamp is ms in fit-tool, local_date_time stays raw seconds.
        fset(activity, "local_timestamp", local_ts + round((end_ms - act_ts) / 1000))
    return activity
