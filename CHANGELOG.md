# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Timestamped progress logging on stderr during decode/merge/encode
  (`-v` debug, `-q` quiet)
- Colorized CLI output: validation marks, bold headlines, dim details;
  honors `NO_COLOR`, disabled when piped
- Box-drawn side-by-side comparison table: each source activity next to
  the merged result
- Same-sport guard: merging different activity types is rejected

### Changed

- Merge output shows only validation checks; the full stats dump stays in
  `fit-stitch validate`
- Merging now walks inputs at the wire level and copies untouched records
  through as their original bytes, decoding into typed messages only where
  fields are actually rewritten. Merging two 20 000-record files drops from
  49 s and 1.5 GB of memory to 1.5 s and 65 MB. Output and CLI behaviour are
  unchanged; record preservation is now byte-for-byte by construction

## [0.1.0] - 2026-08-16

### Added

- N-file FIT activity merge with distance / accumulated-power re-offsetting,
  lap and split renumbering, and split-summary merging
- Single rebuilt session and activity: time-weighted averages, summed totals,
  Normalized Power / IF / TSS recomputed from the merged power stream
- Automatic output validation against the official Garmin FIT SDK
- Optional TCX export
- `fit-stitch` CLI with `merge` (default) and `validate` commands
- Synthetic-fixture test suite (no real FIT data in the repo)
