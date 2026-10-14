import pandas as pd
import streamlit as st

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
    return f"background-color: {BRICK_SOFT}; color: {BRICK}; font-weight: 600;"


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
            preview = pd.read_csv(uploaded)
            st.markdown(
                f'<p class="tm-hint">{len(preview)} rows read. '
                "Validation is added in a later stage.</p>",
                unsafe_allow_html=True,
            )
            st.dataframe(preview, hide_index=True, use_container_width=True)
            st.button("Confirm import", disabled=True, help="Enabled in a later stage")

with tab_cases:
    with st.container(border=True):
        st.markdown('<p class="tm-section">Test cases</p>', unsafe_allow_html=True)
        st.markdown(
            '<p class="tm-hint">Turn test cases on or off. Changes are not saved yet.</p>',
            unsafe_allow_html=True,
        )
        st.data_editor(
            SAMPLE_CASES,
            disabled=["Test case ID", "Name", "Page", "Steps", "Expected result"],
            hide_index=True,
            use_container_width=True,
        )

with tab_run:
    with st.container(border=True):
        st.markdown('<p class="tm-section">Start a run</p>', unsafe_allow_html=True)
        app_url = st.text_input("Application URL", placeholder="https://your-app.example.com")
        selected = st.multiselect(
            "Test cases to run",
            SAMPLE_CASES["Test case ID"].tolist(),
            default=SAMPLE_CASES["Test case ID"].tolist(),
        )
        if st.button("Start run"):
            if not app_url:
                st.error("Enter an application URL first.")
            else:
                st.success(
                    f"Ready to run {len(selected)} test case(s) against {app_url}. "
                    "The worker is added in a later stage."
                )

with tab_reports:
    with st.container(border=True):
        st.markdown('<p class="tm-section">Last run report</p>', unsafe_allow_html=True)
        st.selectbox("Run", ["Run 1 (sample)"])
        styled = SAMPLE_RESULTS.style.map(status_style, subset=["Status"])
        st.dataframe(styled, hide_index=True, use_container_width=True)
        chosen = st.selectbox("Test case video", SAMPLE_RESULTS["Test case ID"].tolist())
        st.markdown(
            f'<p class="tm-hint">The video for {chosen} appears here once the worker records runs.</p>',
            unsafe_allow_html=True,
        )