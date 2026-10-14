import pandas as pd
import streamlit as st
from core.csv_import import validate_csv_text
from core.importer import import_csv_text
from core.runs import create_run
from core.test_cases import list_test_cases, set_enabled
from pathlib import Path
import subprocess
import sys
from core.runs import create_run, get_run_results, list_runs

st.set_page_config(page_title="Test management", layout="wide")

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
SERIF = "Georgia, 'Times New Roman', serif"

st.markdown(
    f"""
<style>
.stApp {{ background: {IVORY}; }}
header[data-testid="stHeader"] {{ background: transparent; }}
.block-container {{
    max-width: 100% !important; padding: 1.5rem 3rem 3rem 3rem !important;
}}

.tm-hero {{
    background: {NAVY}; border-bottom: 3px solid {GOLD};
    border-radius: 14px; padding: 22px 28px; margin-bottom: 18px;
    display: flex; justify-content: space-between; align-items: center;
}}
.tm-title {{
    font-family: {SERIF} !important; font-size: 30px !important;
    color: #FFFFFF !important; margin: 0 !important; font-weight: 400 !important;
}}
.tm-sub {{
    font-size: 15px !important; color: #E9DDBF !important;
    margin: 0 !important;
}}

.tm-card {{
    background: {CARD}; border: 1px solid {LINE}; border-left: 4px solid {GOLD};
    border-radius: 14px; padding: 18px 22px; margin-bottom: 8px;
}}
.tm-card.fail {{ background: {BRICK_SOFT}; border-left-color: {BRICK}; }}
.tm-label {{
    font-size: 14px !important; color: {MUTED} !important;
    margin: 0 !important; font-weight: 400 !important;
}}
.tm-value {{
    font-family: {SERIF} !important; font-size: 34px !important;
    color: {NAVY} !important; margin: 6px 0 0 0 !important; font-weight: 400 !important;
}}
.tm-card.fail .tm-value {{ color: {BRICK} !important; }}

.tm-section {{
    font-family: {SERIF} !important; font-size: 22px !important; color: {NAVY} !important;
    margin: 4px 0 12px 0 !important; font-weight: 400 !important;
}}
.tm-hint {{
    font-size: 15px !important; color: {MUTED} !important; margin: 0 0 12px 0 !important;
}}

div[data-baseweb="tab-list"] {{ gap: 28px; border-bottom: 1px solid {LINE}; }}
button[data-baseweb="tab"] {{ font-size: 15px !important; color: {MUTED} !important; }}
button[data-baseweb="tab"][aria-selected="true"] {{
    color: {NAVY} !important; font-weight: 600 !important;
}}
div[data-baseweb="tab-highlight"] {{ background: {GOLD} !important; height: 3px !important; }}

.stButton > button, .stDownloadButton > button {{
    background: {NAVY}; color: #FFFFFF; border: none;
    border-radius: 10px; padding: 0.55rem 1.3rem; font-size: 15px;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    background: {NAVY_SOFT}; color: #FFFFFF; border: none;
}}
.stButton > button:focus, .stDownloadButton > button:focus {{ box-shadow: none; }}
.stButton > button:disabled {{ background: #C9CDD6; color: #FFFFFF; }}
</style>
""",
    unsafe_allow_html=True,
)

TEMPLATE_CSV = (
    "test_case_id,test_case_name,page,steps,expected_result,enabled\n"
    "TC001,Timesheet week navigation,/timesheet,Click the Next week button,Next week is displayed,Yes\n"
)

SAMPLE_CASES = pd.DataFrame([
    {"Test case ID": "TC001", "Name": "Timesheet week navigation", "Page": "/timesheet",
     "Steps": "Click the Next week button", "Expected result": "Next week is displayed", "Enabled": True},
    {"Test case ID": "TC002", "Name": "Validate hours over 24", "Page": "/timesheet",
     "Steps": "Enter 25 in the Hours field; Click the Save button",
     "Expected result": "Validation error is displayed", "Enabled": True},
    {"Test case ID": "TC003", "Name": "Save timesheet", "Page": "/timesheet",
     "Steps": "Enter 8 in the Hours field; Click the Save button",
     "Expected result": "Timesheet saves successfully", "Enabled": True},
])

SAMPLE_RESULTS = pd.DataFrame([
    {"Test case ID": "TC001", "Status": "Passed", "Failed step": "", "Error": "", "Duration (s)": 4.2},
    {"Test case ID": "TC002", "Status": "Failed", "Failed step": 2,
     "Error": "Could not find button 'Save'", "Duration (s)": 6.8},
    {"Test case ID": "TC003", "Status": "Passed", "Failed step": "", "Error": "", "Duration (s)": 5.1},
])


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


st.markdown(
    '<div class="tm-hero">'
    '<p class="tm-title">Test management</p>'
    '<p class="tm-sub">Last run: 14 Oct, 14:31</p>'
    "</div>",
    unsafe_allow_html=True,
)

tab_dash, tab_upload, tab_cases, tab_run, tab_reports = st.tabs(
    ["Dashboard", "Upload CSV", "Test cases", "Start run", "Reports"]
)

with tab_dash:
    passed = int((SAMPLE_RESULTS["Status"] == "Passed").sum())
    failed = int((SAMPLE_RESULTS["Status"] == "Failed").sum())
    c1, c2, c3 = st.columns(3, gap="large")
    with c1:
        st.markdown(metric_card("Test cases", len(SAMPLE_CASES)), unsafe_allow_html=True)
    with c2:
        st.markdown(metric_card("Passed in last run", passed), unsafe_allow_html=True)
    with c3:
        st.markdown(metric_card("Failed in last run", failed, "fail"), unsafe_allow_html=True)
    st.markdown(
        '<p class="tm-hint">Start a new run from the Start run tab.</p>',
        unsafe_allow_html=True,
    )

with tab_upload:
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
                st.dataframe(pd.DataFrame(result.rows), hide_index=True, use_container_width=True)
                if st.button("Confirm import"):
                    _, saved = import_csv_text(content)
                    st.success(f"Saved {saved} test case(s).")
            else:
                st.error("Nothing was saved. Fix these rows and upload again:")
                for error in result.errors:
                    st.markdown(f"- {error}")

with tab_cases:
    with st.container(border=True):
        st.markdown('<p class="tm-section">Test cases</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tm-hint">Turn a test case on or off. The change saves immediately.</p>',
            unsafe_allow_html=True,
        )
        cases = list_test_cases()
        if not cases:
            st.info("No test cases yet. Upload a CSV in the Upload CSV tab.")
        else:
            table = pd.DataFrame(cases)
            edited = st.data_editor(
                table,
                disabled=["test_case_id", "test_case_name", "page", "steps", "expected_result"],
                hide_index=True,
                use_container_width=True,
                key="cases_editor",
            )
            for _, row in edited.iterrows():
                original = table.loc[table["test_case_id"] == row["test_case_id"], "enabled"].iloc[0]
                if bool(row["enabled"]) != bool(original):
                    set_enabled(row["test_case_id"], bool(row["enabled"]))
                    st.rerun()

with tab_run:
    with st.container(border=True):
        st.markdown('<p class="tm-section">Start a run</p>', unsafe_allow_html=True)
        cases = list_test_cases()
        enabled_ids = [c["test_case_id"] for c in cases if c["enabled"]]
        app_url = st.text_input("Application URL", placeholder="https://your-app.example.com")
        if not enabled_ids:
            st.info("No enabled test cases. Turn some on in the Test cases tab.")
        else:
            selected = st.multiselect("Test cases to run", enabled_ids, default=enabled_ids)
            if st.button("Start run"):
                try:
                    run_id, queued = create_run(app_url, selected)
                    subprocess.Popen(
                        [sys.executable, "-m", "worker.runner"],
                        cwd=str(Path(__file__).parent),
                        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                    )
                    st.success(
                        f"Run {run_id} started with {queued} test(s). "
                        "Open the Reports tab to see results as they finish."
                    )
                except ValueError as error:
                    st.error(str(error))

with tab_reports:
    with st.container(border=True):
        st.markdown('<p class="tm-section">Run report</p>', unsafe_allow_html=True)
        runs = [r for r in list_runs() if r["total"] > 0]
        if not runs:
            st.info("No runs yet. Start one from the Start run tab.")
        else:
            labels = {r["id"]: f"Run {r['id']}  {r['app_url']}  ({r['status']})" for r in runs}
            run_id = st.selectbox("Run", list(labels), format_func=lambda i: labels[i])
            results = get_run_results(run_id)
            df = pd.DataFrame([
                {
                    "Test case ID": r["test_case_id"],
                    "Name": r["test_case_name"],
                    "Status": r["status"].capitalize(),
                    "Failed step": "" if r["failed_step"] is None else str(r["failed_step"]),
                    "Error": r["error_message"] or "",
                    "Duration (s)": round((r["duration_ms"] or 0) / 1000, 2),
                }
                for r in results
            ])
            styled = df.style.map(status_style, subset=["Status"]).format({"Duration (s)": "{:.2f}"})
            st.dataframe(styled, hide_index=True, width="stretch")

            playable = [r for r in results if r["video_path"]]
            if playable:
                choice = st.selectbox("Test case video", [r["test_case_id"] for r in playable])
                chosen = next(r for r in playable if r["test_case_id"] == choice)
                if Path(chosen["video_path"]).exists():
                    st.video(chosen["video_path"])
                else:
                    st.warning("The video file for this test isn't on this machine.")
            else:
                st.markdown(
                    '<p class="tm-hint">No videos for this run yet.</p>',
                    unsafe_allow_html=True,
                )