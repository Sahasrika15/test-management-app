import pytest
from playwright.sync_api import sync_playwright

from core.step_interpreter import interpret, interpret_steps
from worker.action_dispatcher import run_plans
from worker.operations import ERROR, FAILED, NEEDS_REVIEW, PASSED


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


def load(page, html):
    """Load fixture HTML and clear the flags that tests use to prove an action ran."""
    page.set_content(html)
    page.evaluate("window.clicked = undefined; window.key = undefined;")


def run(page, steps, timeout_ms=3000):
    return run_plans(page, "http://example.test", interpret_steps(steps), timeout_ms)


def test_click_then_check_passes(page):
    load(page, "<button onclick=\"this.textContent='Done'; window.clicked=true\">Save</button>")
    outcome = run(page, "Click Save; Check that Done is displayed")
    assert outcome.status == PASSED
    assert page.evaluate("window.clicked") is True


def test_failed_expectation_reports_step(page):
    load(page, "<p>Saved</p>")
    outcome = run(page, "Check that Missing is displayed", timeout_ms=500)
    assert outcome.status == FAILED
    assert outcome.step == 1


def test_negative_check_passes_when_hidden(page):
    load(page, '<p style="display:none">Error</p>')
    assert run(page, "Check that Error is not displayed").status == PASSED


def test_negative_check_fails_when_visible(page):
    load(page, "<p>Error</p>")
    assert run(page, "Check that Error is not displayed", timeout_ms=500).status == FAILED


def test_fill_then_value_check(page):
    load(page, '<label for="h">Hours</label><input id="h">')
    outcome = run(page, "Enter 25 in Hours field; Check that the Hours field has value 25")
    assert outcome.status == PASSED
    assert page.evaluate("document.getElementById('h').value") == "25"


def test_wrong_value_fails(page):
    load(page, '<label for="h">Hours</label><input id="h" value="8">')
    outcome = run(page, "Check that the Hours field has value 25", timeout_ms=500)
    assert outcome.status == FAILED
    assert "expected '25'" in outcome.reason


def test_read_only_check_passes(page):
    load(page, '<label for="a">Amount</label><input id="a" readonly value="1">')
    assert run(page, "Check that Amount is read only").status == PASSED


def test_ambiguous_target_is_never_clicked(page):
    load(page, '<button onclick="window.clicked=true">Submit</button>'
               '<button onclick="window.clicked=true">Submit</button>')
    outcome = run(page, "Click Submit")
    assert outcome.status == NEEDS_REVIEW
    assert page.evaluate("window.clicked") is None


def test_unknown_step_blocks_the_whole_test(page):
    load(page, '<button onclick="window.clicked=true">Save</button>')
    outcome = run(page, "Click Save; teleport | text=X")
    assert outcome.status == NEEDS_REVIEW
    assert outcome.step == 2
    assert page.evaluate("window.clicked") is None


def test_policy_refused_step_needs_review(page):
    load(page, "<p>x</p>")
    assert run(page, "evaluate | text=x | 1").status == NEEDS_REVIEW


def test_missing_click_target_is_error(page):
    load(page, "<p>x</p>")
    outcome = run(page, "Click Nowhere button", timeout_ms=500)
    assert outcome.status == ERROR
    assert outcome.step == 1


def test_delayed_text_is_polled_until_it_appears(page):
    load(page, "<script>setTimeout(() => { const p = document.createElement('p');"
               " p.textContent = 'Ready'; document.body.appendChild(p); }, 400)</script>")
    assert run(page, "Check that Ready is displayed", timeout_ms=3000).status == PASSED


def test_delayed_text_times_out_as_failure(page):
    load(page, "<script>setTimeout(() => { const p = document.createElement('p');"
               " p.textContent = 'Late'; document.body.appendChild(p); }, 1500)</script>")
    assert run(page, "Check that Late is displayed", timeout_ms=300).status == FAILED


def test_wait_for_element_to_disappear(page):
    load(page, '<p id="l">Loading</p><script>setTimeout(() => '
               'document.getElementById("l").remove(), 400)</script>')
    assert run(page, "Wait for Loading to disappear", timeout_ms=3000).status == PASSED


def test_fixed_wait(page):
    load(page, "<p>x</p>")
    assert run(page, "Wait 100 milliseconds").status == PASSED


def test_key_press_reaches_the_page(page):
    load(page, '<input id="i" onkeydown="window.key = event.key">')
    page.focus("#i")
    assert run(page, "Press Enter").status == PASSED
    assert page.evaluate("window.key") == "Enter"


def test_stops_after_first_failure(page):
    load(page, '<button onclick="window.clicked=true">Save</button>')
    outcome = run(page, "Check that Missing is displayed; Click Save", timeout_ms=500)
    assert outcome.status == FAILED
    assert outcome.step == 1
    assert page.evaluate("window.clicked") is None


def test_unknown_plan_is_not_executed():
    plan = interpret("teleport | text=Save")
    assert plan.status == "needs_review"