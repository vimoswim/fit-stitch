"""FIT message identifiers and summary-field combining rules."""

# Global message numbers (FIT profile)
FILE_ID = 0
SESSION = 18
LAP = 19
RECORD = 20
EVENT = 21
ACTIVITY = 34
FILE_CREATOR = 49
TIME_IN_ZONE = 216
SPLIT = 312
SPLIT_SUMMARY = 313

# FIT invalid-value sentinels for integer base types. If either side of a
# combine is one of these, the field is treated as not comparable and the
# first file's raw value is kept.
SENTINELS = {0x7F, 0xFF, 0x7FFF, 0xFFFF, 0x7FFFFFFF, 0xFFFFFFFF}

# total_* fields that must NOT be blindly summed by the generic rule.
SUM_EXCEPTIONS = {
    "total_elapsed_time",
    "total_timer_time",
    "total_distance",
    "total_training_effect",
    "total_anaerobic_training_effect",
}

# Fields where "combined" means the maximum, not a sum (0-5 scales, peaks).
MAX_NOT_SUM = {
    "total_training_effect",
    "total_anaerobic_training_effect",
    "training_load_peak",
}

# Fields that are summable but don't match the total_ prefix.
EXPLICIT_SUM = {"metabolic_calories", "stand_count", "time_standing", "num_splits"}

# Fields the merger sets explicitly (or that must keep the first file's value);
# the generic combiner never touches these.
KEEP_FIRST = {
    "timestamp",
    "start_time",
    "start_position_lat",
    "start_position_long",
    "message_index",
    "first_lap_index",
    "num_laps",
    "sport",
    "sub_sport",
    "sport_profile_name",
    "event",
    "event_type",
    "trigger",
    "threshold_power",
    "left_right_balance",
    "nec_lat",
    "nec_long",
    "swc_lat",
    "swc_long",
    "end_position_lat",
    "end_position_long",
    "normalized_power",
    "intensity_factor",
    "training_stress_score",
    "split_type",
}
