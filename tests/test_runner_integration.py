import functools
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest
from playwright.sync_api import sync_playwright

from worker import runner
from worker.operations import ERROR, FAILED, NEEDS_REVIEW, PASSED

PAGE = """
<button onclick="this.textContent='Done'">Save</button>
<label for="h">Hours</label><input id="h">
<p>Hello</p>
"""


@pytest.fixture(scope="module")
def site(tmp_path_factory):
    root = tmp_path_factory.mktemp("site")
    (root / "index.html").write_text(PAGE, encoding="utf-8")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *args: None
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture(autouse=True)
def short_timeout(monkeypatch):
    monkeypatch.setattr(runner, "STEP_TIMEOUT_MS", 500)


def row(steps, page="/index.html"):
    return {"test_case_id": "T1", "page": page, "steps": steps}


def test_passing_row_runs_and_records_video(browser, site):
    status, failed_step, error, video, duration = runner.run_test(
        browser, site, 1, row("Click Save; Check that Done is displayed; "
                              "Enter 25 in Hours field; Check that the Hours field has value 25"))
    assert status == PASSED
    assert failed_step is None and error is None
    assert video and len(video) > 1000
    assert duration >= 0


def test_failing_expectation_reports_step_and_page(browser, site):
    status, failed_step, error, video, _ = runner.run_test(
        browser, site, 1, row("Check that Hello is displayed; Check that Missing is displayed"))
    assert status == FAILED
    assert failed_step == 2
    assert "Step 2 'Check that Missing is displayed'" in error
    assert "index.html" in error


def test_unrecognized_step_is_not_run(browser, site):
    status, failed_step, error, video, _ = runner.run_test(
        browser, site, 1, row("Teleport to the moon"))
    assert status == NEEDS_REVIEW
    assert failed_step == 1
    assert "not a recognized instruction" in error
    assert video is None


def test_policy_refused_step_is_not_run(browser, site):
    status, _, error, _, _ = runner.run_test(
        browser, site, 1, row("Upload sample.csv to the File field"))
    assert status == NEEDS_REVIEW
    assert "reads local files" in error


def test_missing_element_is_an_error_not_a_failure(browser, site):
    status, failed_step, error, _, _ = runner.run_test(
        browser, site, 1, row("Enter 5 in Nowhere field"))
    assert status == ERROR
    assert failed_step == 1


def test_secret_is_resolved_but_never_stored(browser, site, monkeypatch):
    monkeypatch.setenv("TEST_PASS", "s3cret-value")
    status, _, error, _, _ = runner.run_test(
        browser, site, 1, row("Enter ${TEST_PASS} in Nowhere field", page="/index.html"))
    assert status == ERROR
    assert "s3cret-value" not in error
    assert "${TEST_PASS}" in error


def test_row_without_page_runs_steps_only(browser, site):
    status, _, _, _, _ = runner.run_test(
        browser, site, 1, row("Check that Hello is displayed", page=""))
    # No page was opened, so the blank browser page does not contain Hello.
    assert status in (FAILED, ERROR)