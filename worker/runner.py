import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from core.csv_import import match_step
from core.runs import claim_next_run, finish_run, get_queued_results, save_result

VIDEO_DIR = Path("artifacts/videos")
TIMEOUT_MS = 10000


def first_line(error):
    lines = str(error).strip().splitlines()
    return lines[0] if lines else error.__class__.__name__


def perform(page, step):
    parsed = match_step(step)
    if parsed is None:
        raise ValueError("step is not a known pattern")
    action = parsed["action"]
    if action == "click":
        page.get_by_role("button", name=parsed["name"], exact=True).click(timeout=TIMEOUT_MS)
    elif action == "enter":
        page.get_by_label(parsed["field"], exact=True).fill(parsed["value"], timeout=TIMEOUT_MS)
    elif action == "select":
        page.get_by_label(parsed["field"], exact=True).select_option(parsed["value"], timeout=TIMEOUT_MS)
    elif action in ("check_text", "wait_for"):
        page.get_by_text(parsed["text"]).first.wait_for(state="visible", timeout=TIMEOUT_MS)


def run_test(browser, base_url, run_id, row):
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    context = browser.new_context(
        record_video_dir=str(VIDEO_DIR),
        record_video_size={"width": 1280, "height": 720},
    )
    page = context.new_page()
    video = page.video
    started = time.time()
    failed_step = None
    error = None

    try:
        page.goto(base_url.rstrip("/") + row["page"], timeout=30000)
    except Exception as exc:
        failed_step, error = 0, f"Page did not load: {first_line(exc)}"

    if error is None:
        steps = [s.strip() for s in row["steps"].split(";") if s.strip()]
        for number, step in enumerate(steps, start=1):
            try:
                perform(page, step)
            except Exception as exc:
                failed_step, error = number, f"Step {number} '{step}': {first_line(exc)}"
                break

    context.close()
    video_path = None
    if video:
        target = VIDEO_DIR / f"run{run_id}_{row['test_case_id']}.webm"
        video.save_as(str(target))
        video.delete()
        video_path = str(target)

    duration_ms = int((time.time() - started) * 1000)
    status = "failed" if error else "passed"
    return status, failed_step, error, video_path, duration_ms


def process_all_queued_runs():
    while True:
        run = claim_next_run()
        if run is None:
            print("No more queued runs.")
            return
        print(f"Running execution {run['id']} against {run['app_url']}")
        rows = get_queued_results(run["id"])
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                for row in rows:
                    status, failed_step, error, video, duration = run_test(
                        browser, run["app_url"], run["id"], row
                    )
                    save_result(row["id"], status, failed_step, error, video, duration)
                    line = f"  {row['test_case_id']}  {status}  {duration} ms"
                    print(line + (f"  {error}" if error else ""))
            finally:
                browser.close()
        finish_run(run["id"])
        print(f"Execution {run['id']} finished.")


if __name__ == "__main__":
    process_all_queued_runs()