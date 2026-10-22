"""Worker. A test whose ID starts with LOGIN is the run's login. It runs first. If it passes,
its browser state and session ID are shared with every other test in the run. Credentials come
from .env through ${NAME} placeholders, never from the UI or the database."""
import os
import re
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from core.runs import claim_run, finish_run, get_queued_results, save_result
from core.step_interpreter import interpret, interpret_steps
from worker.action_dispatcher import run_plans
from worker.operations import ERROR, NEEDS_REVIEW, PASSED, first_line

load_dotenv()

VIDEO_DIR = Path("artifacts/videos")
SCREEN_DIR = Path("artifacts/screenshots")
STEP_TIMEOUT_MS = int(os.getenv("STEP_TIMEOUT_MS", "5000"))
STEP_PAUSE_MS = int(os.getenv("STEP_PAUSE_MS", "700"))
VIDEO_TAIL_MS = int(os.getenv("VIDEO_TAIL_MS", "3000"))
LOGIN_PREFIX = "LOGIN"
PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def resolve(text):
    """Replace ${NAME} with the value of that environment variable."""
    return PLACEHOLDER.sub(lambda m: os.getenv(m.group(1), ""), text)


def mask_env(text, names):
    """Show ${NAME} instead of the value of an environment variable in stored text."""
    for name in names:
        secret = os.getenv(name, "")
        if secret:
            text = text.replace(secret, "${" + name + "}")
    return text


def clean_base_url(url):
    raw = (url or "").strip()
    if raw.startswith("http://"):
        raw = "https://" + raw[len("http://") :]
    elif not raw.startswith("https://"):
        raw = "https://" + raw
    parts = urlsplit(raw)
    path = parts.path.rstrip("/")
    return f"https://{parts.netloc}{path}"


def page_url(base_url, page_path):
    sub = "/" + page_path.strip("/") if page_path.strip("/") else ""
    base = base_url.rstrip("/")
    return (base + sub) if sub else (base + "/")


def with_session(url, session_id):
    """Add the session ID that the application keeps in its URL, once a login has produced one."""
    if not session_id:
        return url
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}session={session_id}"


def session_from(url):
    return parse_qs(urlsplit(url).query).get("session", [None])[0]


def is_login_row(row):
    return row["test_case_id"].strip().upper().startswith(LOGIN_PREFIX)


def build_plans(row, base_url, session_id=None):
    plans = []
    page_path = (row.get("page") or "").strip()
    target = with_session(page_url(base_url, page_path), session_id)
    plans.append(interpret("Go to " + target))
    plans.extend(interpret_steps(resolve(row["steps"])))
    return plans


def run_test(browser, base_url, run_id, row, login_state=None, session_id=None, capture=None):
    """Run one row. Returns (status, failed_step, error, video_bytes, duration_ms).
    If capture is a dict and the row passes, the browser state and session ID are stored in it."""
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)

    names = PLACEHOLDER.findall(row["steps"])
    offset = 1
    plans = build_plans(row, base_url, session_id)

    for number, plan in enumerate(plans, start=1):
        if not plan.ok:
            return NEEDS_REVIEW, number - offset, f"Not run: {mask_env(plan.reason, names)}", None, 0

    options = {
        "record_video_dir": str(VIDEO_DIR),
        "record_video_size": {"width": 1280, "height": 720},
        "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "viewport": {"width": 1280, "height": 720},
    }
    if login_state:
        options["storage_state"] = login_state
    context = browser.new_context(**options)
    page = context.new_page()
    page.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    video = page.video
    started = time.time()

    outcome = run_plans(page, base_url, plans, STEP_TIMEOUT_MS, pause_ms=STEP_PAUSE_MS)

    status, failed_step, error = outcome.status, None, None
    if outcome.status != PASSED:
        failed_step = max(outcome.step - offset, 0)
        if failed_step == 0:
            label = "Page did not load"
        else:
            label = f"Step {failed_step} '{plans[outcome.step - 1].step}'"
        error = mask_env(f"{label}: {outcome.reason} (ended on {page.url})", names)
    elif capture is not None:
        capture["state"] = context.storage_state()
        capture["session"] = session_from(page.url)

    try:
        page.screenshot(path=str(SCREEN_DIR / f"run{run_id}_{row['test_case_id']}.png"))
    except Exception:
        pass
    try:
        page.wait_for_timeout(VIDEO_TAIL_MS)
    except Exception:
        pass

    page.close()
    context.close()

    video_bytes = None
    if video:
        try:
            tmp_path = Path(video.path())
            video_bytes = tmp_path.read_bytes()
            if row.get("id"):
                try:
                    (VIDEO_DIR / f"result_{row['id']}.webm").write_bytes(video_bytes)
                except Exception:
                    pass
            tmp_path.unlink(missing_ok=True)
        except Exception:
            video_bytes = None

    duration_ms = int((time.time() - started) * 1000)
    return status, failed_step, error, video_bytes, duration_ms


def execute_row(browser, base_url, run_id, row, login_state=None, session_id=None, capture=None):
    try:
        return run_test(browser, base_url, run_id, row, login_state, session_id, capture)
    except Exception as exc:
        return ERROR, 0, f"Runner error: {first_line(exc)}", None, 0


def report(row, result):
    status, failed_step, error, video, duration = result
    save_result(row["id"], status, failed_step, error, video, duration)
    line = f"  {row['test_case_id']}  {status}  {duration} ms"
    print(line + (f"  {error}" if error else ""), flush=True)


def process_run(run_id):
    """Run one specific execution, then stop. It never picks up other runs."""
    run = claim_run(run_id)
    if run is None:
        print(f"Execution {run_id} is not queued; nothing to do.", flush=True)
        return

    rows = []
    done = set()
    worker_error = None

    try:
        run["app_url"] = clean_base_url(run["app_url"])
        print(f"Running execution {run_id} against {run['app_url']}", flush=True)
        if os.getenv("APP_USER"):
            print(f"  Login user for this run: {os.getenv('APP_USER')}", flush=True)
        rows = get_queued_results(run_id)
        logins = [r for r in rows if is_login_row(r)]
        tests = [r for r in rows if not is_login_row(r)]

        is_headless = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=is_headless,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            try:
                state, session, login_error = None, None, None

                for row in logins:
                    capture = {}
                    result = execute_row(browser, run["app_url"], run_id, row, None, None, capture)
                    report(row, result)
                    done.add(row["id"])
                    if result[0] == PASSED and capture.get("state"):
                        state, session = capture["state"], capture.get("session")
                        print(f"  Login passed; session {session or 'none in URL'} "
                              "is shared with the other tests", flush=True)
                    else:
                        login_error = login_error or result[2] or "login did not pass"

                for row in tests:
                    if login_error:
                        result = (ERROR, 0, f"Login failed: {login_error}", None, 0)
                    else:
                        result = execute_row(browser, run["app_url"], run_id, row, state, session)
                    report(row, result)
                    done.add(row["id"])
            finally:
                browser.close()
    except Exception as exc:
        worker_error = first_line(exc)
        print(f"  Worker error: {worker_error}", flush=True)
    finally:
        for row in rows:
            if row["id"] not in done:
                reason = (f"Worker stopped: {worker_error}" if worker_error
                          else "Runner stopped before this test ran; run again")
                save_result(row["id"], ERROR, 0, reason, None, 0)
                print(f"  {row['test_case_id']}  error  {reason}", flush=True)
        finish_run(run_id)
        print(f"Execution {run_id} finished.", flush=True)


if __name__ == "__main__":
    import sys

    if "--run" not in sys.argv:
        print("Usage: python -m worker.runner --run <execution id>", flush=True)
        sys.exit(1)
    process_run(int(sys.argv[sys.argv.index("--run") + 1]))