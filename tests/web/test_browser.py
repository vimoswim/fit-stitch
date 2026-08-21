"""The browser build, driven end to end in Chromium.

Everything below the UI is covered by the Python suite; what these tests pin is
the part only a browser can prove: that Pyodide boots, that the wheels install,
that a user who drops two files gets a valid FIT back, and that a bad pairing
surfaces as a readable message instead of a dead page.
"""

import datetime
import http.server
import os
import socket
import threading
from pathlib import Path

import pytest

from tests.conftest import make_activity

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "web"
# This container ships a browser at a fixed path; elsewhere (CI, a laptop)
# Playwright resolves its own. Set FIT_STITCH_CHROMIUM to override.
CHROMIUM = os.environ.get("FIT_STITCH_CHROMIUM") or next(
    (p for p in Path("/opt/pw-browsers").glob("chromium-*/chrome-linux/chrome")), None
)
BOOT_TIMEOUT_MS = 240_000

pytestmark = pytest.mark.web


def pytest_configure(config):  # pragma: no cover - registered in pyproject too
    config.addinivalue_line("markers", "web: browser tests (need Chromium)")


@pytest.fixture(scope="session")
def server():
    """Serve web/ over http; Pyodide refuses to run from file:// URLs."""
    if not (WEB / "public" / "pyodide" / "pyodide.mjs").is_file():
        pytest.skip("run scripts/build-web-assets.sh first")

    handler = type(
        "Handler",
        (http.server.SimpleHTTPRequestHandler,),
        {
            "__init__": lambda self, *a, **kw: http.server.SimpleHTTPRequestHandler.__init__(
                self, *a, directory=str(WEB), **kw
            ),
            "log_message": lambda *a: None,
        },
    )
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


@pytest.fixture(scope="session")
def browser():
    playwright = pytest.importorskip("playwright.sync_api")
    launch = {"executable_path": str(CHROMIUM)} if CHROMIUM else {}
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(**launch)
        yield browser
        browser.close()


@pytest.fixture
def page(browser, server):
    page = browser.new_page()
    page.goto(f"{server}/demo/", wait_until="domcontentloaded")
    page.wait_for_function("window.FIT_STITCH_READY === true")
    yield page
    page.close()


def rides(tmp_path, gap_minutes=6):
    t0 = datetime.datetime(2026, 6, 1, 9, 0, tzinfo=datetime.UTC)
    return [
        make_activity(tmp_path / "a.fit", start=t0, power=200, n_laps=2),
        make_activity(
            tmp_path / "b.fit",
            start=t0 + datetime.timedelta(minutes=gap_minutes),
            power=100,
            n_laps=2,
        ),
    ]


def choose(page, paths):
    page.set_input_files("#picker", [str(p) for p in paths])


def test_a_user_can_merge_two_rides_and_download_the_result(page, tmp_path):
    choose(page, rides(tmp_path))
    assert page.locator("#files li").count() == 2

    page.click("#go")
    page.wait_for_selector("#resultPanel:not(.hidden)", timeout=BOOT_TIMEOUT_MS)

    assert "120 records" in page.text_content("#headline")
    assert "0.96 km" in page.text_content("#headline")

    header = page.locator("#comparison thead th").all_text_contents()
    assert header == ["", "a.fit", "b.fit", "merged"]
    distance = page.locator("#comparison tbody tr", has_text="distance").first
    assert distance.locator("td").all_text_contents() == [
        "distance",
        "0.48 km",
        "0.48 km",
        "0.96 km",
    ]

    checks = page.locator("#checks li").all_text_contents()
    assert checks, "no validation checks rendered"
    assert not any("✗" in c for c in checks), checks

    with page.expect_download() as download:
        page.click("#download")
    saved = tmp_path / "merged.fit"
    download.value.save_as(saved)
    assert saved.read_bytes()[8:12] == b".FIT"


def test_progress_is_streamed_while_the_merge_runs(page, tmp_path):
    choose(page, rides(tmp_path))
    page.click("#go")
    page.wait_for_selector("#resultPanel:not(.hidden)", timeout=BOOT_TIMEOUT_MS)

    log = page.text_content("#log")
    assert "decoding 1/2" in log
    assert "rebuilding session/activity" in log


def test_overlapping_activities_are_reported_to_the_user(page, tmp_path):
    """Same ride twice: the page must explain, not hang or blank out."""
    paths = rides(tmp_path)
    choose(page, [paths[0], paths[0]])

    page.click("#go")
    page.wait_for_selector("#errorPanel:not(.hidden)", timeout=BOOT_TIMEOUT_MS)

    assert "overlap" in page.text_content("#errorText")
    assert page.locator("#resultPanel").is_hidden()


def test_tcx_export_is_offered_when_requested(page, tmp_path):
    choose(page, rides(tmp_path))
    page.check("#tcx")

    page.click("#go")
    page.wait_for_selector("#resultPanel:not(.hidden)", timeout=BOOT_TIMEOUT_MS)

    with page.expect_download() as download:
        page.click("#downloadTcx")
    saved = tmp_path / "merged.tcx"
    download.value.save_as(saved)
    assert b"TrainingCenterDatabase" in saved.read_bytes()
