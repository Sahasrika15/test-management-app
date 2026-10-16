"""Phase F: the worker. Reads queued results, runs each row's steps through the
interpreter, dispatcher, and assertion engine, and stores the outcome and video.

Steps may reference secrets as ${NAME}; the value is read from .env at run time
and is never stored or printed. The page in a row, if given, is opened first.
"""
import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from core.runs import claim_next_run, finish_run, get_queued_results, recover_stale_runs, save_result
from core.step_interpreter import interpret, interpret_steps
from worker.action_dispatcher import run_plans
from worker.operations import ERROR, NEEDS_REVIEW, PASSED, first_line

load_dotenv()

VIDEO_DIR = Path("artifacts/videos")
SCREEN_DIR = Path("artifacts/screenshots")
STEP_TIMEOUT_MS = int(os.getenv("STEP_TIMEOUT_MS", "5000"))
PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def resolve(text):
    """Replace ${NAME} with the value of that environment variable."""
    return PLACEHOLDER.sub(lambda m: os.getenv(m.group(1), ""), text)


def mask(text, names):
    """Replace secret values with their ${NAME} form before anything is stored or printed."""
    for name in names:
        secret = os.getenv(name, "")
        if secret:
            text = text.replace(secret, "${" + name + "}")
    return text


def clean_base_url(url):
    parts = urlsplit((url or "").strip())
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def page_url(base_url, page_path):
    """Join the application URL and a row's page path without duplicating the path."""
    page_path = "/" + page_path.strip("/")
    base = base_url.rstrip("/")
    return base if base.endswith(page_path) else base + page_path


def build_plans(row, base_url):
    """Interpret one row. The page, if given, becomes the first plan."""
    plans = []
    if row["page"].strip():
        plans.append(interpret("Go to " + page_url(base_url, row["page"])))
    plans.extend(interpret_steps(resolve(row["steps"])))
    return plans


def run_test(browser, base_url, run_id, row):
    """Run one row. Returns (status, failed_step, error, video_bytes, duration_ms)."""
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)

    names = PLACEHOLDER.findall(row["steps"])
    offset = 1 if row["page"].strip() else 0
    plans = build_plans(row, base_url)

    # Refuse before opening a browser if any step cannot be run.
    for number, plan in enumerate(plans, start=1):
        if not plan.ok:
            reason = mask(plan.reason, names)
            return NEEDS_REVIEW, number - offset, f"Not run: {reason}", None, 0

    context = browser.new_context(
        record_video_dir=str(VIDEO_DIR),
        record_video_size={"width": 1280, "height": 720},
    )
    page = context.new_page()
    video = page.video
    started = time.time()

    outcome = run_plans(page, base_url, plans, STEP_TIMEOUT_MS)

    status, failed_step, error = outcome.status, None, None
    if outcome.status != PASSED:
        failed_step = max(outcome.step - offset, 0)
        if failed_step == 0:
            label = "Page did not load"
        else:
            label = f"Step {failed_step} '{plans[outcome.step - 1].step}'"
        error = mask(f"{label}: {outcome.reason} (ended on {page.url})", names)

    try:
        page.screenshot(path=str(SCREEN_DIR / f"run{run_id}_{row['test_case_id']}.png"))
    except Exception:
        pass
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    page.close()
    context.close()

    video_bytes = None
    if video:
        try:
            tmp_path = Path(video.path())
            video_bytes = tmp_path.read_bytes()
            tmp_path.unlink(missing_ok=True)
        except Exception:
            video_bytes = None

    duration_ms = int((time.time() - started) * 1000)
    return status, failed_step, error, video_bytes, duration_ms


def process_all_queued_runs():
    recover_stale_runs()
    while True:
        run = claim_next_run()
        if run is None:
            print("No more queued runs.", flush=True)
            return

        run_id = run["id"]
        rows = []
        done = set()

        try:
            run["app_url"] = clean_base_url(run["app_url"])
            print(f"Running execution {run_id} against {run['app_url']}", flush=True)
            rows = get_queued_results(run_id)

            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                try:
                    for row in rows:
                        try:
                            status, failed_step, error, video, duration = run_test(
                                browser, run["app_url"], run_id, row
                            )
                        except Exception as exc:
                            status, failed_step, error, video, duration = (
                                ERROR, 0, f"Runner error: {first_line(exc)}", None, 0
                            )
                        save_result(row["id"], status, failed_step, error, video, duration)
                        done.add(row["id"])
                        line = f"  {row['test_case_id']}  {status}  {duration} ms"
                        print(line + (f"  {error}" if error else ""), flush=True)
                finally:
                    browser.close()
        except Exception as exc:
            print(f"  Worker error: {first_line(exc)}", flush=True)
        finally:
            for row in rows:
                if row["id"] not in done:
                    save_result(
                        row["id"], ERROR, 0,
                        "Runner stopped before this test ran; run again",
                        None, 0,
                    )
                    print(f"  {row['test_case_id']}  error  Runner stopped before this test ran", flush=True)
            finish_run(run_id)
            print(f"Execution {run_id} finished.", flush=True)


if __name__ == "__main__":
    process_all_queued_runs()