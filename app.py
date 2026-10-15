import subprocess
import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from core.csv_import import validate_csv_text
from core.importer import import_csv_text
from core.runs import create_run, get_dashboard_stats, get_result_video, get_run_results, list_runs
from core.test_cases import list_sources, list_test_cases, set_enabled

st.set_page_config(page_title="Verity - Plain words. Proven results.", layout="wide")

NAVY = "#1F2A44"
NAVY_SOFT = "#2E3D5E"
GOLD = "#B8893B"
GOLD_SOFT = "#F5EBD7"
IVORY = "#FAF7F0"
CARD = "#FFFFFF"
LINE = "#E4DCCB"
MUTED = "#6B6F7A"
BRICK = "#8E2F2A"
BRICK_SOFT = "#F7E4E1"
NEUTRAL_SOFT = "#EEF1F6"
SERIF = "Georgia, 'Times New Roman', serif"
CARD_HEIGHT = 440

st.markdown(
    f"""
<style>
.stApp {{
    background: radial-gradient(circle at top right, #FFFFFF 0%, {IVORY} 45%, #F3EEE2 100%);
}}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{
    max-width: 100% !important; padding: 1.2rem 3.2rem 3rem 3.2rem !important;
}}

.tm-hero {{
    background: linear-gradient(135deg, {NAVY} 0%, {NAVY_SOFT} 100%);
    border-bottom: 3px solid {GOLD};
    border-radius: 18px; padding: 26px 32px; margin-bottom: 22px;
    display: flex; justify-content: space-between; align-items: center;
    box-shadow: 0 10px 30px rgba(31,42,68,0.18);
}}
.tm-title {{
    font-family: {SERIF} !important; font-size: 32px !important;
    color: #FFFFFF !important; margin: 0 !important; font-weight: 400 !important;
    letter-spacing: 0.3px;
}}
.tm-sub {{
    font-size: 14px !important; color: #E9DDBF !important; margin: 0 !important;
    background: rgba(255,255,255,0.08); padding: 6px 14px; border-radius: 999px;
}}

.tm-card {{
    background: #FFFFFF; border: 1px solid {LINE}; border-left: 4px solid {GOLD};
    border-radius: 16px; padding: 20px 24px; margin-bottom: 8px;
    box-shadow: 0 4px 14px rgba(31,42,68,0.06);
    transition: transform .2s ease, box-shadow .2s ease;
}}
.tm-card:hover {{ transform: translateY(-2px); box-shadow: 0 10px 22px rgba(31,42,68,0.10); }}
.tm-card.fail {{
    background: linear-gradient(135deg, #FFFFFF 0%, {BRICK_SOFT} 100%);
    border-left-color: {BRICK};
}}
.tm-label {{
    font-size: 13px !important; color: {MUTED} !important; margin: 0 !important;
    font-weight: 500 !important; text-transform: uppercase; letter-spacing: 0.8px;
}}
.tm-value {{
    font-family: {SERIF} !important; font-size: 40px !important; color: {NAVY} !important;
    margin: 6px 0 0 0 !important; font-weight: 400 !important;
}}
.tm-card.fail .tm-value {{ color: {BRICK} !important; }}

.tm-section {{
    font-family: {SERIF} !important; font-size: 24px !important; color: {NAVY} !important;
    margin: 2px 0 4px 0 !important; font-weight: 400 !important;
}}
.tm-section::after {{
    content: ""; display: block; width: 48px; height: 3px;
    background: {GOLD}; border-radius: 2px; margin-top: 6px;
}}
.tm-hint {{
    font-size: 15px !important; color: {MUTED} !important; margin: 0 0 14px 0 !important;
}}

div[data-baseweb="tab-list"] {{ gap: 8px; border-bottom: 1px solid {LINE}; }}
button[data-baseweb="tab"] {{
    font-size: 15px !important; color: {MUTED} !important; padding: 10px 18px !important;
    border-radius: 10px 10px 0 0 !important; transition: background .2s ease;
}}
button[data-baseweb="tab"]:hover {{ background: {GOLD_SOFT}; color: {NAVY} !important; }}
button[data-baseweb="tab"][aria-selected="true"] {{ color: {NAVY} !important; font-weight: 600 !important; }}
div[data-baseweb="tab-highlight"] {{ background: {GOLD} !important; height: 3px !important; border-radius: 3px; }}

[data-testid="stVerticalBlockBorderWrapper"] {{
    background: #FFFFFF; border-radius: 18px !important;
    box-shadow: 0 6px 24px rgba(31,42,68,0.07); padding: 6px 8px;
}}

.stButton > button, .stDownloadButton > button {{
    background: linear-gradient(135deg, {NAVY} 0%, {NAVY_SOFT} 100%);
    color: #FFFFFF; border: none; border-radius: 12px;
    padding: 0.6rem 1.4rem; font-size: 15px; font-weight: 500;
    box-shadow: 0 6px 16px rgba(31,42,68,0.20);
    transition: transform .15s ease, box-shadow .15s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    transform: translateY(-1px); box-shadow: 0 10px 22px rgba(31,42,68,0.28);
    color: #FFFFFF; border: none;
}}
.stButton > button:focus, .stDownloadButton > button:focus {{
    box-shadow: 0 0 0 3px {GOLD_SOFT}; color: #FFFFFF;
}}
.stButton > button:disabled {{ background: #C9CDD6; box-shadow: none; }}

div[data-baseweb="input"] > div, div[data-baseweb="select"] > div {{
    border-radius: 12px !important; border-color: {LINE} !important; background: {IVORY};
}}
div[data-baseweb="input"]:focus-within > div, div[data-baseweb="select"]:focus-within > div {{
    border-color: {GOLD} !important; box-shadow: 0 0 0 3px {GOLD_SOFT};
}}

[data-testid="stDataFrame"], [data-testid="stDataEditor"] {{
    border-radius: 14px; overflow: hidden; border: 1px solid {LINE};
}}
div[data-testid="stAlert"] {{ border-radius: 14px; }}
div[data-testid="stFileUploaderDropzone"] {{
    border-radius: 16px; border: 2px dashed {GOLD}; background: {IVORY};
}}
div[data-testid="stColumn"] video {{
    width: 100% !important; height: 240px !important;
    object-fit: contain; background: #0B0F1A; border-radius: 12px;
}}
</style>
""",
    unsafe_allow_html=True,
)

TEMPLATE_CSV = (
    "test_case_id,test_case_name,page,steps,expected_result,enabled\n"
    "TC001,Timesheet week navigation,/timesheet,Click the Next week button,Next week is displayed,Yes\n"
)


def metric_card(label, value, variant=""):
    return (
        f'<div class="tm-card {variant}">'
        f'<p class="tm-label">{label}</p>'
        f'<p class="tm-value">{value}</p></div>'
    )


def status_style(value):
    if value == "Passed":
        return f"background-color: {GOLD_SOFT}; color: {NAVY}; font-weight: 600;"
    if value == "Failed":
        return f"background-color: {BRICK_SOFT}; color: {BRICK}; font-weight: 600;"
    return f"color: {MUTED};"


def go_to(page_name):
    st.session_state["nav"] = page_name


def confirm_import(content, source_name):
    _, saved = import_csv_text(content, source_file=source_name)
    st.session_state["nav"] = "Test cases"
    st.session_state["view_source_box"] = source_name
    st.session_state["flash"] = f"Saved {saved} test case(s) from {source_name}."


def start_run():
    app_url = st.session_state.get("start_url", "")
    source = st.session_state.get("view_source_box")
    enabled = [c["test_case_id"] for c in list_test_cases(source) if c["enabled"]]
    selected = [c for c in st.session_state.get("start_cases", enabled) if c in enabled]
    try:
        run_id, queued = create_run(app_url, selected)
    except ValueError as error:
        st.session_state["start_error"] = str(error)
        return

    log_dir = Path("artifacts/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = open(log_dir / "worker.log", "a", encoding="utf-8")
    subprocess.Popen(
        [sys.executable, "-m", "worker.runner"],
        cwd=str(Path(__file__).parent),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        creationflags=(
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        ),
    )
    st.session_state["start_error"] = None
    st.session_state["nav"] = "Reports"
    st.session_state["rep_run"] = run_id
    st.session_state["flash"] = (
        f"Run {run_id} started with {queued} test(s). Results appear as each test finishes."
    )


def result_card(r, run_id):
    status = r["status"]
    badges = {
        "passed": ("Passed", GOLD_SOFT, NAVY),
        "failed": ("Failed", BRICK_SOFT, BRICK),
    }
    badge, badge_bg, badge_fg = badges.get(status, (status.capitalize(), NEUTRAL_SOFT, MUTED))

    if status == "passed":
        actual = "All steps completed."
    elif status == "failed":
        step_no = r["failed_step"]
        reason = r["error_message"] or "no reason was recorded"
        actual = f"Stopped at step {step_no}: {reason}" if step_no is not None else reason
    else:
        actual = "Not run yet. The worker has not picked this test up."

    seconds = (r["duration_ms"] or 0) / 1000

    with st.container(border=True, height=CARD_HEIGHT):
        st.markdown(
            f'<div style="display:flex; justify-content:space-between; align-items:center; gap:12px;">'
            f'<span style="font-family:{SERIF}; font-size:18px; color:{NAVY};">'
            f'{r["test_case_id"]}  {r["test_case_name"]}</span>'
            f'<span style="background:{badge_bg}; color:{badge_fg}; padding:4px 12px; '
            f'border-radius:999px; font-size:13px; font-weight:600; white-space:nowrap;">{badge}</span>'
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<p class="tm-hint" style="margin-top:10px;">'
            f"<b>Expected:</b> {r['expected_result']}<br>"
            f"<b>Actual:</b> {actual}<br>"
            f"<b>Duration:</b> {seconds:.2f} s</p>",
            unsafe_allow_html=True,
        )
        has_disk_file = bool(r["video_path"]) and Path(r["video_path"]).exists()
        if r["has_video"] or has_disk_file:
            if st.toggle("Play video", key=f"play_{run_id}_{r['test_case_id']}"):
                data = get_result_video(r["id"]) if r["has_video"] else None
                if data:
                    st.video(data, format="video/webm")
                elif has_disk_file:
                    st.video(r["video_path"])
                else:
                    st.caption("Video could not be loaded.")
        else:
            st.caption("No video file found for this test.")


def render_reports(live):
    with st.container(border=True):
        st.markdown('<p class="tm-section">Run report</p>', unsafe_allow_html=True)
        runs = [r for r in list_runs() if r["total"] > 0]
        if not runs:
            st.info("No runs yet. Start one from the Start run tab.")
            return

        active = any(r["status"] in ("queued", "running") for r in runs)
        if live and not active:
            # The run has finished, so switch back to the static view and stop polling.
            st.rerun(scope="app")

        top, _ = st.columns([4, 1])
        with top:
            labels = {r["id"]: f"Run {r['id']}  {r['app_url']}  ({r['status']})" for r in runs}
            run_id = st.selectbox("Run", list(labels), format_func=lambda i: labels[i], key="rep_run")

        results = get_run_results(run_id)

        passed_n = sum(1 for r in results if r["status"] == "passed")
        failed_n = sum(1 for r in results if r["status"] == "failed")
        s1, s2, s3 = st.columns(3, gap="large")
        with s1:
            st.markdown(metric_card("Tests in run", len(results)), unsafe_allow_html=True)
        with s2:
            st.markdown(metric_card("Passed", passed_n), unsafe_allow_html=True)
        with s3:
            st.markdown(metric_card("Failed", failed_n, "fail" if failed_n else ""), unsafe_allow_html=True)

        search = st.text_input("Search videos", placeholder="Type a test case ID or name", key="video_search")
        query = search.strip().lower()
        filtered = [
            r for r in results
            if not query
            or query in r["test_case_id"].lower()
            or query in r["test_case_name"].lower()
        ]
        st.markdown(
            f'<p class="tm-hint">Showing {len(filtered)} of {len(results)} tests</p>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<p class="tm-section" style="margin-top:12px;">Test results</p>',
            unsafe_allow_html=True,
        )
        if not filtered:
            st.info("No tests match your search.")
        for i in range(0, len(filtered), 2):
            cols = st.columns(2, gap="large")
            for col, r in zip(cols, filtered[i:i + 2]):
                with col:
                    result_card(r, run_id)


@st.fragment(run_every="2s")
def live_reports():
    render_reports(live=True)


@st.fragment
def static_reports():
    render_reports(live=False)


runs_with_results = [r for r in list_runs() if r["total"] > 0]
_last_at = runs_with_results[0]["created_at"] if runs_with_results else None
_last_label = f"Last run: {_last_at:%d %b, %H:%M}" if _last_at else "No runs yet"

st.markdown(
    '<div class="tm-hero">'
    '<div>'
    '<p class="tm-title">Verity</p>'
    '<p style="font-family:Georgia, \'Times New Roman\', serif; font-size:15px; '
    'color:#F5EBD7; opacity:0.9; margin:6px 0 0 0;">'
    'Plain words. Proven results.</p>'
    '</div>'
    f'<p class="tm-sub">{_last_label}</p>'
    "</div>",
    unsafe_allow_html=True,
)

st.session_state.setdefault("nav", "Dashboard")
page = st.segmented_control(
    "Section",
    ["Dashboard", "Upload CSV", "Test cases", "Start run", "Reports"],
    key="nav",
    label_visibility="collapsed",
) or "Dashboard"

flash = st.session_state.pop("flash", None)
if flash:
    st.success(flash)


if page == "Dashboard":
    stats = get_dashboard_stats()
    t = stats["totals"]
    passed = int(t["passed"])
    failed = int(t["failed"])
    judged = passed + failed
    pass_rate = passed / judged if judged else 0.0
    avg_seconds = float(t["avg_ms"]) / 1000

    c1, c2, c3, c4 = st.columns(4, gap="large")
    with c1:
        st.markdown(
            metric_card("Enabled test cases", f"{t['enabled_cases']} / {t['total_cases']}"),
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(metric_card("Runs", int(t["total_runs"])), unsafe_allow_html=True)
    with c3:
        variant = "fail" if judged and failed > passed else ""
        st.markdown(metric_card("Pass rate", f"{pass_rate:.0%}", variant), unsafe_allow_html=True)
    with c4:
        st.markdown(metric_card("Average duration", f"{avg_seconds:.1f} s"), unsafe_allow_html=True)

    if judged:
        st.progress(pass_rate, text=f"{passed} passed and {failed} failed across all runs")

    if stats["trend"]:
        last = stats["trend"][-1]
        st.markdown(
            f'<p class="tm-hint">Latest run: Run {last["run_id"]} against {last["app_url"]}, '
            f'{last["created_at"]:%d %b %Y, %H:%M}.</p>',
            unsafe_allow_html=True,
        )

    left, right = st.columns([2, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown('<p class="tm-section">Recent runs</p>', unsafe_allow_html=True)
            judged_trend = [
                r for r in stats["trend"]
                if int(r["passed"]) + int(r["failed"]) > 0
            ]
            if judged_trend:
                trend_df = pd.DataFrame([
                    {"Run": f"Run {r['run_id']}", "Passed": int(r["passed"]), "Failed": int(r["failed"])}
                    for r in judged_trend
                ]).set_index("Run")
                st.bar_chart(trend_df, color=[NAVY, BRICK])
            else:
                st.info("No runs with saved results yet. Start a run from the Start run tab and the chart will fill in.")

    with right:
        with st.container(border=True):
            st.markdown('<p class="tm-section">Result split</p>', unsafe_allow_html=True)
            if judged:
                split = pd.DataFrame({"Result": ["Passed", "Failed"], "Count": [passed, failed]})
                donut = (
                    alt.Chart(split)
                    .mark_arc(innerRadius=70)
                    .encode(
                        theta="Count:Q",
                        color=alt.Color(
                            "Result:N",
                            scale=alt.Scale(domain=["Passed", "Failed"], range=[NAVY, BRICK]),
                            legend=alt.Legend(orient="bottom"),
                        ),
                        tooltip=["Result", "Count"],
                    )
                    .properties(height=280)
                )
                st.altair_chart(donut)
            else:
                st.info("No results yet.")

    with st.container(border=True):
        st.markdown('<p class="tm-section">Latest failures</p>', unsafe_allow_html=True)
        if stats["failures"]:
            failure_df = pd.DataFrame([
                {
                    "Run": f"Run {f['run_id']}",
                    "Test case": f"{f['test_case_id']}  {f['test_case_name']}",
                    "Failed step": "" if f["failed_step"] is None else str(f["failed_step"]),
                    "Error": f["error_message"] or "",
                    "When": f["created_at"].strftime("%d %b %H:%M"),
                }
                for f in stats["failures"]
            ])
            st.dataframe(failure_df, hide_index=True, width="stretch")
        else:
            st.success("No failures recorded.")


if page == "Upload CSV":
    with st.container(border=True):
        st.markdown('<p class="tm-section">Upload test cases</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tm-hint">Download the template, fill it in with plain English steps, '
            "then upload it here.</p>",
            unsafe_allow_html=True,
        )
        st.download_button(
            "Download CSV template",
            TEMPLATE_CSV,
            file_name="test_cases_template.csv",
            mime="text/csv",
        )
        uploaded = st.file_uploader("Choose a CSV file", type="csv")
        if uploaded is not None:
            content = uploaded.getvalue().decode("utf-8-sig")
            result = validate_csv_text(content)
            if result.ok:
                st.success(f"{len(result.rows)} valid rows. Ready to import.")
                st.dataframe(pd.DataFrame(result.rows), hide_index=True, width="stretch")
                st.button(
                    "Confirm import",
                    on_click=confirm_import,
                    args=(content, uploaded.name),
                )
            else:
                st.error("Nothing was saved. Fix these rows and upload again:")
                for error in result.errors:
                    st.markdown(f"- {error}")


if page == "Test cases":
    with st.container(border=True):
        st.markdown('<p class="tm-section">Test cases</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tm-hint">Turn a test case on or off. The change saves immediately.</p>',
            unsafe_allow_html=True,
        )
        sources = list_sources()
        if not sources:
            st.info("No test cases yet. Upload a CSV in the Upload CSV tab.")
        else:
            choices = [s["source_file"] or "" for s in sources]
            names = {
                (s["source_file"] or ""): (
                    f"{s['source_file']}  ({s['total']} cases)"
                    if s["source_file"]
                    else f"Earlier imports  ({s['total']} cases)"
                )
                for s in sources
            }
            view = st.selectbox(
                "Showing test cases from",
                choices,
                format_func=lambda c: names[c],
                key="view_source_box",
            )
            cases = list_test_cases(view)
            if not cases:
                st.info("This file has no test cases.")
            else:
                table = pd.DataFrame(cases).drop(columns=["source_file"])
                edited = st.data_editor(
                    table,
                    disabled=["test_case_id", "test_case_name", "page", "steps", "expected_result"],
                    hide_index=True,
                    width="stretch",
                    key=f"cases_editor_{view}",
                )
                for _, row in edited.iterrows():
                    original = table.loc[
                        table["test_case_id"] == row["test_case_id"], "enabled"
                    ].iloc[0]
                    if bool(row["enabled"]) != bool(original):
                        set_enabled(row["test_case_id"], bool(row["enabled"]))
                        st.rerun()
        st.button("Go to Start run", on_click=go_to, args=("Start run",))


if page == "Start run":
    with st.container(border=True):
        st.markdown('<p class="tm-section">Start a run</p>', unsafe_allow_html=True)
        source = st.session_state.get("view_source_box")
        cases = list_test_cases(source) if source else list_test_cases()
        enabled_ids = [c["test_case_id"] for c in cases if c["enabled"]]
        st.text_input(
            "Application URL",
            placeholder="https://your-app.example.com",
            key="start_url",
        )
        if not enabled_ids:
            st.info("No enabled test cases. Turn some on in the Test cases tab.")
        else:
            st.multiselect("Test cases to run", enabled_ids, default=enabled_ids, key="start_cases")
            st.button("Start run", on_click=start_run)
        error = st.session_state.pop("start_error", None)
        if error:
            st.error(error)


if page == "Reports":
    # Poll every 2 seconds only while a run is queued or running. Otherwise show a static view.
    any_active = any(
        r["status"] in ("queued", "running")
        for r in list_runs()
        if r["total"] > 0
    )
    if any_active:
        live_reports()
    else:
        static_reports()