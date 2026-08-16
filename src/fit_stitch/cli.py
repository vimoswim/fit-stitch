"""fit-stitch command line interface.

Usage:
    fit-stitch ride1.fit ride2.fit [more.fit ...] -o merged.fit [--tcx] [--no-validate]
    fit-stitch validate file.fit
"""

import argparse
import sys
from pathlib import Path

from fit_stitch import __version__
from fit_stitch.merge import MergeError, merge_files
from fit_stitch.tcx import export_tcx
from fit_stitch.validate import ValidationReport, validate_fit

EXIT_OK = 0
EXIT_VALIDATION_FAILED = 1
EXIT_ERROR = 2


def _print_report(report: ValidationReport) -> None:
    for name, passed, detail in report.checks:
        mark = "✓" if passed else "✗"
        print(f"  {mark} {name}" + (f" ({detail})" if detail else ""))
    if report.stats:
        print("  stats:")
        for k, v in report.stats.items():
            print(f"    {k}: {v}")


def _merge_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="fit-stitch",
        description="Stitch multiple Garmin FIT activity files into one activity.",
    )
    p.add_argument("files", nargs="+", type=Path, help="input FIT files (2 or more)")
    p.add_argument("-o", "--output", type=Path, required=True, help="merged FIT output path")
    p.add_argument("--tcx", action="store_true", help="also write a TCX next to the output")
    p.add_argument("--no-validate", action="store_true", help="skip output validation")
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
            print(f"error: no such file: {args.file}", file=sys.stderr)
            return EXIT_ERROR
        report = validate_fit(args.file)
        print(f"Validation of {args.file}:")
        _print_report(report)
        return EXIT_OK if report.ok else EXIT_VALIDATION_FAILED

    args = _merge_parser().parse_args(argv)
    if len(args.files) < 2:
        print("error: need at least 2 input files to merge", file=sys.stderr)
        return EXIT_ERROR
    for f in args.files:
        if not f.is_file():
            print(f"error: no such file: {f}", file=sys.stderr)
            return EXIT_ERROR

    try:
        stats = merge_files(args.files, args.output)
    except MergeError as e:
        print(f"error: {e}", file=sys.stderr)
        return EXIT_ERROR

    print(
        f"Merged {stats.files} files -> {args.output}: {stats.records} records, "
        f"{stats.laps} laps, {stats.total_distance / 1000:.2f} km, "
        f"timer {stats.total_timer_time:.0f} s"
        + (f", NP {stats.normalized_power} W" if stats.normalized_power else "")
    )

    code = EXIT_OK
    if not args.no_validate:
        report = validate_fit(args.output, expected_sources=args.files)
        print("Validation:")
        _print_report(report)
        if not report.ok:
            print("validation FAILED", file=sys.stderr)
            code = EXIT_VALIDATION_FAILED

    if args.tcx:
        tcx_path = args.output.with_suffix(".tcx")
        n = export_tcx(args.output, tcx_path)
        print(f"TCX written: {tcx_path} ({n} trackpoints)")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
