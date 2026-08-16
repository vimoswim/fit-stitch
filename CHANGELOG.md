# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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
