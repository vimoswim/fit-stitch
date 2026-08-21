"""In-memory entry points for running fit-stitch inside a browser.

The library works on paths, which is exactly right under Pyodide: its virtual
filesystem makes ``merge_files`` usable unchanged, so the browser build runs the
same merge code as the CLI rather than a reimplementation of it. This module is
the thin layer around that — bytes in, bytes and a JSON-safe report out — plus
the two things a page needs that a CLI does not: progress delivered to a
callback instead of stderr, and failures returned as data instead of raised.

Everything is written to a scratch directory that is deleted before returning,
so an activity's GPS trace lives no longer than the call itself.
"""

import contextlib
import dataclasses
import datetime
import logging
import shutil
import tempfile
from pathlib import Path

from fit_stitch import __version__
from fit_stitch.merge import MergeError, merge_files
from fit_stitch.report import build_comparison
from fit_stitch.tcx import export_tcx
from fit_stitch.validate import validate_fit

OUTPUT_NAME = "merged.fit"
TCX_NAME = "merged.tcx"

log = logging.getLogger("fit_stitch")


class _CallbackHandler(logging.Handler):
    """Forward the library's progress lines to a caller-supplied callback.

    The library logs absolute paths, which on this path point into a scratch
    directory the caller never sees. Stripping that prefix leaves the file names
    the user recognises instead of a temporary directory name.
    """

    def __init__(self, callback, strip: str = ""):
        super().__init__(level=logging.INFO)
        self.callback = callback
        self.strip = strip

    def emit(self, record):
        # a failing UI callback must never abort the merge
        with contextlib.suppress(Exception):
            line = self.format(record)
            self.callback(line.replace(self.strip, "") if self.strip else line)


class _Progress:
    """Install the progress handler for the duration of a call, then remove it."""

    def __init__(self, callback, strip: str = ""):
        self.handler = _CallbackHandler(callback, strip) if callback else None

    def __enter__(self):
        if self.handler:
            self.handler.setFormatter(logging.Formatter("%(message)s"))
            log.addHandler(self.handler)
            self._previous = log.level
            if log.level > logging.INFO or log.level == logging.NOTSET:
                log.setLevel(logging.INFO)
        return self

    def __exit__(self, *exc):
        if self.handler:
            log.removeHandler(self.handler)
            log.setLevel(self._previous)
        return False


def _jsonable(value):
    """Make decoder output serializable: datetimes become ISO 8601 strings."""
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, list | tuple):
        return [_jsonable(v) for v in value]
    return value


def _report_dict(report) -> dict:
    return {
        "ok": report.ok,
        "checks": [
            {"name": name, "passed": passed, "detail": detail}
            for name, passed, detail in report.checks
        ],
        "stats": _jsonable(report.stats),
    }


def _safe_name(name: str, index: int) -> str:
    """Strip any path component a browser might hand us."""
    cleaned = Path(str(name or "")).name.strip()
    return cleaned or f"input{index + 1}.fit"


def merge_bytes(files, *, tcx: bool = False, validate: bool = True, on_progress=None) -> dict:
    """Merge ``(name, data)`` pairs and return the output bytes plus a report.

    Returns ``{"ok": False, "error": ...}`` for inputs that cannot be merged —
    overlapping activities, mixed sports, a file that is not a single activity.
    Those are things a user can act on, so they are results, not exceptions.
    """
    if len(files) < 2:
        return {"ok": False, "error": "need at least 2 input files to merge"}

    workdir = Path(tempfile.mkdtemp(prefix="fit-stitch-"))
    try:
        # One directory per input so two files with the same name can both be
        # merged and still show their own name in the comparison table.
        paths = []
        for i, (name, data) in enumerate(files):
            slot = workdir / str(i)
            slot.mkdir()
            path = slot / _safe_name(name, i)
            path.write_bytes(bytes(data))
            paths.append(path)

        out = workdir / OUTPUT_NAME
        with _Progress(on_progress, strip=f"{workdir}/"):
            try:
                stats = merge_files(paths, out)
            except MergeError as e:
                return {"ok": False, "error": str(e)}

            result = {
                "ok": True,
                "error": None,
                "engine": __version__,
                "output_name": OUTPUT_NAME,
                "output": out.read_bytes(),
                "tcx_name": None,
                "tcx": None,
                "summary": _jsonable(dataclasses.asdict(stats)),
                "comparison": build_comparison(stats),
                "validation": None,
            }
            if validate:
                result["validation"] = _report_dict(validate_fit(out, expected_sources=paths))
            if tcx:
                tcx_path = workdir / TCX_NAME
                export_tcx(out, tcx_path)
                result["tcx_name"] = TCX_NAME
                result["tcx"] = tcx_path.read_bytes()
        return result
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def validate_bytes(name: str, data) -> dict:
    """Validate a single FIT activity and return a JSON-safe report.

    ``ok`` is the verdict on the file, not on the call: a file that fails its
    checks still comes back with the full list of what passed and what did not.
    ``error`` is set only when the file could not be read at all.
    """
    workdir = Path(tempfile.mkdtemp(prefix="fit-stitch-"))
    safe = _safe_name(name, 0)
    try:
        path = workdir / safe
        path.write_bytes(bytes(data))
        return {"error": None, "name": safe, **_report_dict(validate_fit(path))}
    except Exception as e:  # a corrupt upload must reach the page as a message
        return {
            "ok": False,
            "error": f"could not read {safe}: {e}",
            "name": safe,
            "checks": [],
            "stats": {},
        }
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
