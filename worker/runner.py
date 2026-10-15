import os
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

from core.csv_import import match_step
from core.runs import claim_next_run, finish_run, get_queued_results, recover_stale_runs, save_result

load_dotenv()

VIDEO_DIR = Path("artifacts/videos")
SCREEN_DIR = Path("artifacts/screenshots")
SESSION_FILE = Path("artifacts/session.json")
STEP_TIMEOUT_MS = int(os.getenv("STEP_TIMEOUT_MS", "5000"))

# APEX shows these while it is saving or refreshing a region.
LOADING_SELECTOR = ".u-Processing, .a-Processing, .apex-loading-indicator, #apex_loading"

GRID_CELL_JS = """
([day, rowText]) => {
    document.querySelectorAll('[data-tm-target]').forEach(e => e.removeAttribute('data-tm-target'));
    const shown = e => { const r = e.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
    const center = e => { const r = e.getBoundingClientRect(); return { x: r.left + r.width / 2, y: r.top + r.height / 2 }; };
    const text = e => (e.innerText || '').trim();
    const elements = [...document.querySelectorAll('body *')].filter(shown);

    const headers = elements.filter(e => {
        const t = text(e).toUpperCase();
        return t.startsWith(day) && t.length <= 14;
    });
    if (!headers.length) return 'no column heading ' + day;
    headers.sort((a, b) => text(a).length - text(b).length);
    const h = center(headers[0]);

    const rows = elements.filter(e => text(e).includes(rowText) && text(e).length <= rowText.length + 40);
    if (!rows.length) return 'no row labelled ' + rowText;
    rows.sort((a, b) => text(a).length - text(b).length);
    const r = center(rows[0]);

    const inputs = [...document.querySelectorAll('input, textarea')].filter(i =>
        shown(i) && !i.disabled && !['hidden', 'checkbox', 'radio', 'button', 'submit'].includes(i.type));

    let best = null;
    let bestScore = Infinity;
    for (const i of inputs) {
        const c = center(i);
        const dy = Math.abs(c.y - r.y);
        const dx = Math.abs(c.x - h.x);
        if (dy > 45) continue;
        const score = dx + dy;
        if (score < bestScore) { bestScore = score; best = i; }
    }
    if (!best) return 'no editable box under ' + day + ' on the row ' + rowText;
    best.setAttribute('data-tm-target', '1');
    return 'ok';
}
"""


def first_line(error):
    lines = str(error).strip().splitlines()
    return lines[0] if lines else error.__class__.__name__


def blocker_reason(error):
    """Keep the first line of a Playwright error plus the lines that explain why a click failed."""
    lines = [line.strip() for line in str(error).strip().splitlines() if line.strip()]
    if not lines:
        return error.__class__.__name__
    keywords = ("intercepts pointer", "not enabled", "not visible", "not stable",
                "outside of the viewport", "disabled", "element is not attached")
    details = [line for line in lines[1:] if any(k in line.lower() for k in keywords)]
    return "; ".join([lines[0]] + details[:2])


def clean_base_url(url):
    parts = urlsplit((url or "").strip())
    path = parts.path.rstrip("/")
    return f"{parts.scheme}://{parts.netloc}{path}"


def build_url(base_url, page_path, session_id):
    page_path = "/" + page_path.strip("/")
    base = base_url.rstrip("/")
    url = base if base.endswith(page_path) else base + page_path
    if session_id:
        url += f"?session={session_id}"
    return url


def visible(locator):
    return locator.filter(visible=True).first


def field(page, label):
    return (
        page.get_by_label(label, exact=True)
        .or_(page.get_by_placeholder(label, exact=True))
        .filter(visible=True)
        .first
    )


def first_visible(locator):
    """Return the first matching element that is actually on screen, or None.
    Checks each match in Python, so hidden duplicates (for example, a mobile copy of a button) are skipped."""
    try:
        count = locator.count()
    except Exception:
        return None
    for i in range(count):
        item = locator.nth(i)
        try:
            if item.is_visible():
                return item
        except Exception:
            continue
    return None


def button(page, name):
    """Find a visible control with this text. Tries role, then text inside any element, waiting up to the step timeout."""
    text_pattern = re.compile(rf"^\s*{re.escape(name)}\s*$", re.IGNORECASE)
    loose_pattern = re.compile(re.escape(name), re.IGNORECASE)
    candidates = [
        page.get_by_role("button", name=name, exact=True),
        page.get_by_role("button", name=loose_pattern),
        page.get_by_text(text_pattern),
        page.locator("button, a, [role=button], input[type=button], input[type=submit]")
            .filter(has_text=loose_pattern),
    ]
    deadline = time.time() + STEP_TIMEOUT_MS / 1000
    while True:
        for candidate in candidates:
            found = first_visible(candidate)
            if found is not None:
                return found
        if time.time() >= deadline:
            raise RuntimeError(f"no visible control with the text '{name}'")
        page.wait_for_timeout(250)


def wait_for_page_idle(page):
    """Wait until APEX's loading indicator has gone. Does nothing if the page has no indicator."""
    try:
        page.locator(LOADING_SELECTOR).first.wait_for(state="hidden", timeout=STEP_TIMEOUT_MS)
    except Exception:
        pass


def click_control(page, name):
    """Click a visible control. If Playwright cannot click it normally, try a script click and
    report the blocking reason only when both attempts fail."""
    wait_for_page_idle(page)
    target = button(page, name)

    try:
        if not target.is_enabled():
            raise RuntimeError(f"button '{name}' is disabled on this page")
    except RuntimeError:
        raise
    except Exception:
        pass

    try:
        target.click(timeout=STEP_TIMEOUT_MS)
        return
    except Exception as exc:
        reason = blocker_reason(exc)

    try:
        target.scroll_into_view_if_needed(timeout=STEP_TIMEOUT_MS)
        target.evaluate("el => el.click()")
        return
    except Exception:
        raise RuntimeError(f"could not click '{name}': {reason}")


def login_applies(base_url):
    scope = os.getenv("LOGIN_BASE_URL", "").strip().rstrip("/")
    return bool(scope) and base_url.rstrip("/").startswith(scope)


def login(browser, base_url):
    if not login_applies(base_url):
        return None
    username = os.getenv("LOGIN_USERNAME", "").strip()
    if not username:
        return None

    password = os.getenv("LOGIN_PASSWORD", "")
    login_page = os.getenv("LOGIN_PAGE", "/login")
    user_label = os.getenv("LOGIN_USER_LABEL", "Username")
    pass_label = os.getenv("LOGIN_PASSWORD_LABEL", "Password")
    btn = os.getenv("LOGIN_BUTTON", "Sign In")

    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    context = browser.new_context()
    page = context.new_page()
    try:
        page.goto(base_url.rstrip("/") + login_page, wait_until="domcontentloaded", timeout=60000)
        try:
            field(page, user_label).fill(username, timeout=STEP_TIMEOUT_MS)
        except Exception as exc:
            raise RuntimeError(f"username field '{user_label}' not found") from exc
        try:
            field(page, pass_label).fill(password, timeout=STEP_TIMEOUT_MS)
        except Exception as exc:
            raise RuntimeError(f"password field '{pass_label}' not found") from exc
        try:
            button(page, btn).click(timeout=STEP_TIMEOUT_MS)
        except Exception as exc:
            raise RuntimeError(f"button '{btn}' not found") from exc

        try:
            page.wait_for_url(lambda url: "/login" not in url, timeout=60000)
        except Exception as exc:
            raise RuntimeError("still on the login page after clicking the button") from exc

        match = re.search(r"session=(\d+)", page.url)
        session_id = match.group(1) if match else None
        context.storage_state(path=str(SESSION_FILE))
    finally:
        context.close()
    return session_id


def fill_grid_cell(page, value, day, row_text):
    result = page.evaluate(GRID_CELL_JS, [day, row_text])
    if result != "ok":
        raise RuntimeError(result)
    target = page.locator("[data-tm-target='1']").first
    target.fill(value, timeout=STEP_TIMEOUT_MS)
    # Tab out so the grid commits the value before the next step (APEX saves on blur).
    target.press("Tab")
    wait_for_page_idle(page)
MESSAGES_JS = """
() => {
    const sel = "[role=alert], [class*=error], [class*=Error], [class*=alert], [class*=Alert], " +
                "[class*=notification], [class*=Notification], [class*=invalid], [class*=Invalid]";
    const seen = new Set();
    const out = [];
    for (const e of document.querySelectorAll(sel)) {
        const r = e.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = (e.innerText || '').trim().replace(/\\s+/g, ' ');
        if (!t || t.length > 200 || seen.has(t)) continue;
        seen.add(t);
        out.push(t);
        if (out.length >= 8) break;
    }
    return out;
}
"""


def visible_messages(page):
    """Return the error or alert text currently visible on the page, for diagnostics."""
    try:
        return page.evaluate(MESSAGES_JS)
    except Exception:
        return []

def perform(page, step):
    parsed = match_step(step)
    if parsed is None:
        raise ValueError("step is not a known pattern")
    action = parsed["action"]
    if action == "cell":
        fill_grid_cell(page, parsed["value"], parsed["day"], parsed["row"])
    elif action == "click":
        click_control(page, parsed["name"])
    elif action == "enter":
        field(page, parsed["field"]).fill(parsed["value"], timeout=STEP_TIMEOUT_MS)
    elif action == "select":
        field(page, parsed["field"]).select_option(parsed["value"], timeout=STEP_TIMEOUT_MS)
    elif action in ("check_text", "wait_for"):
        locator = visible(page.get_by_text(parsed["text"]))
        try:
            locator.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
        except Exception:
            shown = visible_messages(page)
            if shown:
                hint = "Messages on screen: " + " || ".join(shown)
            else:
                hint = "No error or alert messages on screen"
            raise RuntimeError(f"text '{parsed['text']}' not visible. {hint}")

def run_test(browser, base_url, run_id, row, session_id):
    VIDEO_DIR.mkdir(parents=True, exist_ok=True)
    SCREEN_DIR.mkdir(parents=True, exist_ok=True)

    options = {
        "record_video_dir": str(VIDEO_DIR),
        "record_video_size": {"width": 1280, "height": 720},
    }
    if session_id and SESSION_FILE.exists():
        options["storage_state"] = str(SESSION_FILE)

    context = browser.new_context(**options)
    page = context.new_page()
    video = page.video
    started = time.time()
    failed_step = None
    error = None

    target = build_url(base_url, row["page"], session_id)
    try:
        page.goto(target, wait_until="domcontentloaded", timeout=60000)
    except Exception as exc:
        failed_step, error = 0, f"Page did not load: {first_line(exc)}"

    if error is None and "/login" in page.url and "/login" not in target:
        failed_step, error = 0, "Session not accepted: the page redirected to the login page"

    if error is None:
        steps = [s.strip() for s in row["steps"].split(";") if s.strip()]
        for number, step in enumerate(steps, start=1):
            try:
                perform(page, step)
                # Small operational pacing between actions makes playback legible
                page.wait_for_timeout(250)
            except Exception as exc:
                failed_step, error = number, f"Step {number} '{step}': {first_line(exc)}"
                break

    if error:
        failed_step = 0 if failed_step is None else failed_step
        error += f" (ended on {page.url})"

    try:
        page.screenshot(path=str(SCREEN_DIR / f"run{run_id}_{row['test_case_id']}.png"))
    except Exception:
        pass

    # Give the video recorder 1.5 seconds to capture the final UI state
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass

    # Proper sequence to finalize video encoding:
    # 1. Close page first
    page.close()
    # 2. Close context
    context.close()

    video_path = None
    if video:
        out = VIDEO_DIR / f"run{run_id}_{row['test_case_id']}.webm"
        try:
            # Playwright finalizes recording upon page/context close
            video.save_as(str(out))
            video.delete()
            video_path = str(out)
        except Exception:
            # Fallback to existing path if save_as encounters a lock
            try:
                video_path = video.path()
            except Exception:
                video_path = None

    duration_ms = int((time.time() - started) * 1000)
    status = "failed" if error else "passed"
    return status, failed_step, error, video_path, duration_ms


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
                    login_error = None
                    session_id = None
                    try:
                        session_id = login(browser, run["app_url"])
                        if session_id:
                            print(f"  Login: performed (session {session_id})", flush=True)
                        elif login_applies(run["app_url"]):
                            print("  Login: performed, no session ID needed", flush=True)
                        else:
                            print("  Login: not required for this application", flush=True)
                    except Exception as exc:
                        login_error = f"Login failed: {first_line(exc)}"
                        print("  " + login_error, flush=True)

                    for row in rows:
                        if login_error:
                            status, failed_step, error, video, duration = "failed", 0, login_error, None, 0
                        else:
                            try:
                                status, failed_step, error, video, duration = run_test(
                                    browser, run["app_url"], run_id, row, session_id
                                )
                            except Exception as exc:
                                status, failed_step, error, video, duration = (
                                    "failed", 0, f"Runner error: {first_line(exc)}", None, 0
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
                        row["id"], "failed", 0,
                        "Runner stopped before this test ran; run again",
                        None, 0,
                    )
                    print(f"  {row['test_case_id']}  failed  Runner stopped before this test ran", flush=True)
            finish_run(run_id)
            print(f"Execution {run_id} finished.", flush=True)


if __name__ == "__main__":
    process_all_queued_runs()