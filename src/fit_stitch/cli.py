"""fit-stitch command line interface.

Usage:
    fit-stitch ride1.fit ride2.fit [more.fit ...] -o merged.fit [--tcx] [--no-validate]
    fit-stitch validate file.fit
"""

import argparse
import datetime
import logging
import os
import sys
from pathlib import Path

from fit_stitch import __version__
from fit_stitch.merge import MergeError, MergeStats, merge_files
from fit_stitch.tcx import export_tcx
from fit_stitch.validate import ValidationReport, validate_fit

EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_ERROR = 2

_ANSI = {
    "green": "\033[32m",
    "red": "\033[31m",
    "cyan": "\033[36m",
    "bold": "\033[1m",
    "dim": "\033[2m",
}
_RESET = "\033[0m"


def _use_color(stream) -> bool:
    return stream.isatty() and "NO_COLOR" not in os.environ and os.environ.get("TERM") != "dumb"


def _paint(text: str, color: str, enabled: bool) -> str:
    return f"{_ANSI[color]}{text}{_RESET}" if enabled else text


def _err(msg: str) -> None:
    print(f"{_paint('error:', 'red', _use_color(sys.stderr))} {msg}", file=sys.stderr)


def _print_report(report: ValidationReport, show_stats: bool = True) -> None:
    c = _use_color(sys.stdout)
    for name, passed, detail in report.checks:
        mark = _paint("✓", "green", c) if passed else _paint("✗", "red", c)
        line = f"  {mark} {name}"
        if detail:
            line += " " + _paint(f"({detail})", "dim", c)
        print(line)
    if show_stats and report.stats:
        print(_paint("  stats:", "bold", c))
        for k, v in report.stats.items():
            print(f"    {_paint(f'{k}:', 'dim', c)} {v}")


def _fmt_dur(sec: float) -> str:
    sec = round(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _fmt_start(ms: int) -> str:
    return datetime.datetime.fromtimestamp(ms / 1000, datetime.UTC).strftime("%H:%M:%S")


_COMPARISON_ROWS = {
    "sport": ("sport", str),
    "start_ms": ("start (UTC)", _fmt_start),
    "distance_m": ("distance", lambda m: f"{m / 1000:.2f} km"),
    "timer_s": ("moving time", _fmt_dur),
    "elapsed_s": ("elapsed time", _fmt_dur),
    "avg_speed_ms": ("avg speed", lambda v: f"{v * 3.6:.1f} km/h"),
    "avg_power": ("avg power", lambda v: f"{v} W"),
    "max_power": ("max power", lambda v: f"{v} W"),
    "normalized_power": ("norm power", lambda v: f"{v} W"),
    "avg_hr": ("avg HR", lambda v: f"{v} bpm"),
    "max_hr": ("max HR", lambda v: f"{v} bpm"),
    "ascent_m": ("ascent", lambda v: f"{v} m"),
    "calories": ("calories", lambda v: f"{v} kcal"),
}


def _print_comparison(stats: MergeStats) -> None:
    """Box-drawn table: one column per input activity, last column = merged."""
    cols = [*stats.sources, stats.merged]
    header = ["", *[c["name"] for c in cols]]
    body = []
    for key, (label, fmt) in _COMPARISON_ROWS.items():
        vals = ["—" if c.get(key) is None else fmt(c[key]) for c in cols]
        if any(v != "—" for v in vals):
            body.append([label, *vals])

    c = _use_color(sys.stdout)
    widths = [max(len(row[i]) for row in [header, *body]) for i in range(len(header))]

    def border(left: str, mid: str, right: str) -> str:
        return _paint(left + mid.join("─" * (w + 2) for w in widths) + right, "dim", c)

    def render(row: list[str], is_header: bool = False) -> str:
        cells = []
        for i, v in enumerate(row):
            cell = v.ljust(widths[i]) if i == 0 else v.rjust(widths[i])
            if is_header:
                cell = _paint(cell, "bold", c)
            elif i == 0:
                cell = _paint(cell, "dim", c)
            elif i == len(row) - 1:
                cell = _paint(cell, "green", c)
            cells.append(cell)
        sep = _paint("│", "dim", c)
        return f"{sep} " + f" {sep} ".join(cells) + f" {sep}"

    print(border("┌", "┬", "┐"))
    print(render(header, is_header=True))
    print(border("├", "┼", "┤"))
    for row in body:
        print(render(row))
    print(border("└", "┴", "┘"))


def _merge_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fit-stitch",
        description="Stitch multiple Garmin FIT activity files into one activity.",
    )
    p.add_argument("files", nargs="+", type=Path, help="input FIT files (2 or more)")
    p.add_argument("-o", "--output", type=Path, required=True, help="merged FIT output path")
    p.add_argument("--tcx", action="store_true", help="also write a TCX next to the output")
    p.add_argument("--no-validate", action="store_true", help="skip output validation")
    p.add_argument("-v", "--verbose", action="store_true", help="debug-level progress logs")
    p.add_argument("-q", "--quiet", action="store_true", help="suppress progress logs")
    p.add_argument("--version", action="version", version=f"fit-stitch {__version__}")
    return p


def _validate_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fit-stitch validate", description="Validate a FIT activity file."
    )
    p.add_argument("file", type=Path, help="FIT file to validate")
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv

    if argv and argv[0] == "validate":
        args = _validate_parser().parse_args(argv[1:])
        if not args.file.is_file():
            _err(f"no such file: {args.file}")
            return EXIT_ERROR
        report = validate_fit(args.file)
        print(f"Validation of {args.file}:")
        _print_report(report)
        return EXIT_OK if report.ok else EXIT_VALIDATION_FAILED

    args = _merge_parser().parse_args(argv)
    level = logging.WARNING if args.quiet else logging.DEBUG if args.verbose else logging.INFO
    ts = _paint("[%(asctime)s]", "dim", _use_color(sys.stderr))
    # force=True: fit_tool installs a root handler on import, which would make
    # a plain basicConfig() a silent no-op
    logging.basicConfig(
        level=level,
        stream=sys.stderr,
        format=f"{ts} %(message)s",
        datefmt="%H:%M:%S",
        force=True,
    )
    if len(args.files) < 2:
        _err("need at least 2 input files to merge")
        return EXIT_ERROR
    for f in args.files:
        if not f.is_file():
            _err(f"no such file: {f}")
            return EXIT_ERROR

    try:
        stats = merge_files(args.files, args.output)
    except MergeError as e:
        _err(str(e))
        return EXIT_ERROR

    c = _use_color(sys.stdout)
    print(
        _paint(f"Merged {stats.files} files -> {args.output}", "bold", c)
        + f": {stats.records} records, "
        f"{stats.laps} laps, {stats.total_distance / 1000:.2f} km, "
        f"timer {stats.total_timer_time:.0f} s"
        + (f", NP {stats.normalized_power} W" if stats.normalized_power else "")
    )
    _print_comparison(stats)

    code = EXIT_OK
    if not args.no_validate:
        logging.getLogger(__name__).info("validating %s (re-decoding all files)", args.output)
        report = validate_fit(args.output, expected_sources=args.files)
        print(_paint("Validation:", "bold", c))
        # basic parameters already shown in the comparison table above
        _print_report(report, show_stats=False)
        if not report.ok:
            print(_paint("validation FAILED", "red", _use_color(sys.stderr)), file=sys.stderr)
            code = EXIT_VALIDATION_FAILED

    if args.tcx:
        tcx_path = args.output.with_suffix(".tcx")
        n = export_tcx(args.output, tcx_path)
        print(f"TCX written: {_paint(str(tcx_path), 'cyan', c)} ({n} trackpoints)")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
