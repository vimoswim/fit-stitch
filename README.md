# fit-stitch

Stitch two or more Garmin FIT activity files — e.g. a ride accidentally saved as two activities — into one spec-compliant activity that Garmin Connect accepts.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![CI](https://github.com/vimoswim/fit-stitch/actions/workflows/ci.yml/badge.svg)](https://github.com/vimoswim/fit-stitch/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](pyproject.toml)

![fit-stitch merging two rides into one activity, with a side-by-side comparison table and validation checks](https://vimoswim.com/images/blog/vimoswim_blog_fit-stitch-cli.webp)

## Why

You press *Save* instead of *Pause* mid-ride (or the device dies and you restart the recording), and one workout ends up as two FIT files. Naively concatenating them doesn't work — each file carries its own `session`, `activity`, lap numbering, a distance channel that restarts at zero, and a CRC. Garmin Connect rejects such combinations. `fit-stitch` decodes the files, rebuilds them as one activity, and re-encodes a valid FIT.

This tool was born from a real 283 km ride accidentally saved as two activities — read the [full story](https://vimoswim.com/stories/stitching-a-split-garmin-ride-back-together-fit-stitch) on the Vimo Swim blog.

Works for any FIT activity — cycling, swimming, running.

## Features

- Merges **2+ FIT activity files** into one, sorted by start time (rejects overlapping inputs and mixed activity types — only same-sport files merge)
- Preserves the **full record stream**: GPS, HR, cadence, power, temperature, cycling dynamics, HRV, gear-change events — including undocumented Garmin messages
- **Re-offsets distance** and accumulated power so file N continues where file N−1 ended; the gap between activities stays a pause in elapsed time
- Rebuilds **one session + one activity**: time-weighted averages, summed totals, max/min fields, and Normalized Power / IF / TSS recomputed from the merged 1 Hz power stream
- Renumbers laps and splits; merges split summaries
- **Auto-validates** the output with the official Garmin FIT SDK (CRC, chronology, monotonic distance, single session/activity, distance sum)
- Colorized CLI with **live progress logs** and a **side-by-side comparison table**: each source activity next to the merged result
- Optional **TCX export** as a fallback

## Quick Start

### Prerequisites

- Python 3.11+

### Installation

```bash
pipx install git+https://github.com/vimoswim/fit-stitch.git
# or: pip install git+https://github.com/vimoswim/fit-stitch.git
```

### Usage

```bash
# Merge (order doesn't matter — files are sorted by start time)
fit-stitch ride-part1.fit ride-part2.fit -o full-ride.fit

# With a TCX fallback next to the output
fit-stitch ride-part1.fit ride-part2.fit -o full-ride.fit --tcx

# Validate any FIT activity file
fit-stitch validate full-ride.fit
```

Progress logs go to stderr (`-q` silences them, `-v` adds debug detail); colors switch off automatically when output is piped or `NO_COLOR` is set.

Then import the merged file in Garmin Connect via **Import Data** (connect.garmin.com/app/import-data). If the source activities already synced, delete them afterwards to avoid double-counted totals.

## How it works

Decode all inputs (`fit-tool`) → copy record streams with running offsets, dropping per-file session/activity structures → rebuild a single session and activity → encode with a fresh header and CRC → validate with the official `garmin-fit-sdk` decoder.

Known limitations: input activities must not overlap in time; the session bounding box assumes the track doesn't cross the antimeridian; summary field rules are tuned for outdoor sports recorded at 1 s intervals.

## Development

```bash
git clone https://github.com/vimoswim/fit-stitch.git
cd fit-stitch
poetry install
poetry run pytest       # tests generate synthetic FIT files — no real data in the repo
poetry run ruff check .
```

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting a PR.

## Security

To report a vulnerability, please see [SECURITY.md](SECURITY.md). Never attach personal FIT files to public issues — they contain GPS traces.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">
  Created by <a href="https://www.linkedin.com/in/mariusz-smenzyk/">Mariusz Smenżyk</a><br>
  Vimo Swim — swim tech, sensors and Garmin tooling<br>
  <a href="https://vimoswim.com">Website</a>
  <span> | </span>
  <a href="https://vimoswim.com/stories">Stories</a><br>
  Crafted by <a href="https://vimoswim.com">vimoswim.com</a>
</div>
