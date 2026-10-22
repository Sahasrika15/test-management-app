"""Flask web application for Verity – replaces the Streamlit app.py."""
import io
import os
import subprocess
import sys
import threading
from pathlib import Path

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from core.csv_import import validate_csv_text
from core.importer import import_csv_text
from core.runs import (
    create_run,
    get_dashboard_stats,
    get_result_video,
    get_run_results,
    list_runs,
)
from core.test_cases import list_sources, list_test_cases, set_enabled

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET", "verity-dev-secret-change-me")

TEMPLATE_CSV = (
    "test_case_id,test_case_name,page,steps,expected_result,enabled\n"
    "TC001,Timesheet week navigation,/timesheet,Click the Next week button,Next week is displayed,Yes\n"
)


# ─── helpers ────────────────────────────────────────────────────────────────
VIDEO_CACHE_DIR = Path("artifacts/videos")
VIDEO_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_result_video_to_disk(result_id):
    cache_path = VIDEO_CACHE_DIR / f"result_{result_id}.webm"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path
    data = get_result_video(result_id)
    if data:
        try:
            cache_path.write_bytes(data)
            return cache_path
        except Exception:
            pass
    return None


def _prefetch_run_videos(results):
    for r in results:
        res_id = r.get("id")
        if res_id and (r.get("has_video") or r.get("video_path")):
            try:
                _cache_result_video_to_disk(res_id)
            except Exception:
                pass

def _spawn_worker(run_id: int, needs_login: bool, username: str, password: str):
    env = dict(os.environ)
    if needs_login:
        env["APP_USER"] = username
        env["APP_PASS"] = password
    log_dir = Path("artifacts/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "worker.log", "a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "-m", "worker.runner", "--run", str(run_id)],
        cwd=str(Path(__file__).parent),
        env=env,
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
    )


# ─── routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/dashboard")
def api_dashboard():
    stats = get_dashboard_stats()
    t = stats["totals"]
    passed = int(t.get("passed", 0) or 0)
    failed = int(t.get("failed", 0) or 0)
    judged = passed + failed
    pass_rate = f"{passed / judged:.0%}" if judged else "—"
    avg_seconds = round(float(t.get("avg_ms", 0) or 0) / 1000, 1)

    return jsonify({
        "totals": t,
        "passed": passed,
        "failed": failed,
        "judged": judged,
        "pass_rate": pass_rate,
        "avg_seconds": avg_seconds,
        "last_label": stats.get("last_label", "No runs yet"),
        "trend": stats.get("trend", []),
        "failures": stats.get("failures", []),
    })


@app.route("/upload", methods=["GET", "POST"])
def upload_csv():
    if request.method == "POST":
        f = request.files.get("csv_file")
        if not f:
            flash("No file selected.", "danger")
            return redirect(url_for("upload_csv"))
        content = f.read().decode("utf-8-sig")
        result = validate_csv_text(content)
        if result.ok:
            _, saved = import_csv_text(content, source_file=f.filename)
            flash(f"Saved {saved} test case(s) from {f.filename}.", "success")
            session["view_source"] = f.filename
            return redirect(url_for("test_cases"))
        else:
            return render_template("upload.html", errors=result.errors, rows=None)
    return render_template("upload.html", errors=None, rows=None)


@app.route("/template.csv")
def download_template():
    return send_file(
        io.BytesIO(TEMPLATE_CSV.encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name="test_cases_template.csv",
    )


@app.route("/test-cases", methods=["GET", "POST"])
def test_cases():
    if request.method == "POST":
        tc_id = request.form.get("test_case_id")
        enabled = request.form.get("enabled") == "1"
        set_enabled(tc_id, enabled)
        return jsonify({"ok": True})

    return render_template("test_cases.html")


@app.route("/api/test-cases")
def api_test_cases():
    sources = list_sources()
    source_choices = [s["source_file"] or "" for s in sources]
    source_names = {
        (s["source_file"] or ""): (
            f"{s['source_file']}  ({s['total']} cases)"
            if s["source_file"]
            else f"Earlier imports  ({s['total']} cases)"
        )
        for s in sources
    }
    view = request.args.get("source", session.get("view_source", source_choices[0] if source_choices else None))
    if view is not None:
        session["view_source"] = view
    cases = list_test_cases(view) if view is not None else list_test_cases()
    return jsonify({
        "sources": source_choices,
        "source_names": source_names,
        "view": view,
        "cases": cases,
    })


@app.route("/start-run", methods=["GET", "POST"])
def start_run():
    if request.method == "POST":
        app_url = request.form.get("app_url", "").strip()
        needs_login = bool(request.form.get("needs_login"))
        username = request.form.get("login_user", "").strip()
        password = request.form.get("login_pass", "")
        selected = request.form.getlist("test_cases")

        # validations
        if needs_login:
            if not username or not password:
                flash("Enter the username and password, or turn off the login option.", "danger")
                return redirect(url_for("start_run"))
            if not any(c.upper().startswith("LOGIN") for c in selected):
                flash(
                    "Login is on, but no LOGIN test case is selected. "
                    "Add a LOGIN row to the CSV and select it.",
                    "danger",
                )
                return redirect(url_for("start_run"))

        try:
            run_id, queued = create_run(app_url, selected)
        except ValueError as e:
            flash(str(e), "danger")
            return redirect(url_for("start_run"))

        _spawn_worker(run_id, needs_login, username, password)
        flash(f"Run {run_id} started with {queued} test(s). Results appear as each test finishes.", "success")
        return redirect(url_for("reports", run_id=run_id))

    return render_template("start_run.html")


@app.route("/api/start-run/cases")
def api_start_run_cases():
    source = session.get("view_source")
    cases = list_test_cases(source) if source else list_test_cases()
    enabled = [c for c in cases if c["enabled"]]
    return jsonify({"cases": enabled})


@app.route("/reports")
def reports():
    initial_run_id = request.args.get("run_id", type=int)
    return render_template("reports.html", initial_run_id=initial_run_id)


@app.route("/api/reports")
def api_reports():
    runs = [r for r in list_runs() if r["total"] > 0]
    if not runs:
        return jsonify({
            "runs": [],
            "results": [],
            "selected_run": None,
            "passed_n": 0,
            "failed_n": 0,
        })

    req_run_id = request.args.get("run_id", type=int)
    valid_ids = {r["id"] for r in runs}
    selected_run = req_run_id if req_run_id in valid_ids else runs[0]["id"]

    results = get_run_results(selected_run)
    passed_n = sum(1 for r in results if r["status"] == "passed")
    failed_n = sum(1 for r in results if r["status"] == "failed")

    serialized_runs = [
        {
            "id": r["id"],
            "app_url": r["app_url"],
            "status": r["status"],
            "total": r["total"],
        }
        for r in runs
    ]

    threading.Thread(target=_prefetch_run_videos, args=(results,), daemon=True).start()

    return jsonify({
        "runs": serialized_runs,
        "selected_run": selected_run,
        "results": results,
        "passed_n": passed_n,
        "failed_n": failed_n,
    })


@app.route("/api/runs")
def api_runs():
    """Polling endpoint: returns the active run statuses."""
    runs = list_runs()
    return jsonify([
        {"id": r["id"], "status": r["status"], "total": r["total"]}
        for r in runs
    ])


@app.route("/api/results/<int:run_id>")
def api_results(run_id):
    results = get_run_results(run_id)
    return jsonify(results)


@app.route("/video/<int:result_id>")
def video(result_id):
    cache_path = _cache_result_video_to_disk(result_id)
    if cache_path and cache_path.exists():
        resp = send_file(
            cache_path,
            mimetype="video/webm",
            as_attachment=False,
            conditional=True,
            download_name=f"recording_{result_id}.webm",
        )
        resp.headers["Accept-Ranges"] = "bytes"
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    data = get_result_video(result_id)
    if not data:
        return "Not found", 404
    resp = send_file(
        io.BytesIO(data),
        mimetype="video/webm",
        as_attachment=False,
        conditional=True,
        download_name=f"recording_{result_id}.webm",
    )
    resp.headers["Accept-Ranges"] = "bytes"
    resp.headers["Cache-Control"] = "public, max-age=86400"
    return resp


if __name__ == "__main__":
    app.run(debug=True, port=5000)
