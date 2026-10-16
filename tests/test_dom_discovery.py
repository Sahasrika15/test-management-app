import pytest
from playwright.sync_api import sync_playwright

from worker.dom_discovery import AMBIGUOUS, FOUND, MISSING, discover


@pytest.fixture(scope="module")
def page():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        pg = browser.new_page()
        yield pg
        browser.close()


GRID_HTML = """
<table>
  <thead><tr><th></th><th>MON 12-Oct</th><th>WED 14-Oct</th></tr></thead>
  <tbody>
    <tr><td>Test Project 2</td><td><input id="m2"></td><td><input id="w2"></td></tr>
    <tr><td>E-Commerce Platform</td><td><input id="m1"></td><td><input id="w1"></td></tr>
  </tbody>
</table>
"""


def test_button_by_name(page):
    page.set_content("<button>Save</button><button>Cancel</button>")
    result = discover(page, "Save")
    assert result.status == FOUND
    assert result.locator.inner_text() == "Save"


def test_exact_name_wins_over_substring(page):
    page.set_content("<button>Save draft</button><button>Save</button>")
    result = discover(page, "Save")
    assert result.status == FOUND
    assert result.locator.inner_text() == "Save"


def test_link_label_and_placeholder(page):
    page.set_content('<a href="#">Help</a><label for="u">Username</label>'
                     '<input id="u"><input placeholder="Search project">')
    assert discover(page, "Help").status == FOUND
    user = discover(page, "Username")
    assert user.status == FOUND
    assert user.locator.evaluate("e => e.id") == "u"
    assert discover(page, "Search project").status == FOUND


def test_visible_text(page):
    page.set_content("<p>Your timesheet was saved</p>")
    result = discover(page, "timesheet was saved")
    assert result.status == FOUND


def test_duplicate_visible_buttons_are_ambiguous(page):
    page.set_content("<button>Submit</button><button>Submit</button>")
    result = discover(page, "Submit")
    assert result.status == AMBIGUOUS
    assert result.count == 2
    assert result.locator is None


def test_hidden_duplicate_is_ignored(page):
    page.set_content('<button style="display:none">Submit</button><button>Submit</button>')
    result = discover(page, "Submit")
    assert result.status == FOUND
    assert result.count == 1


def test_missing_element_is_reported(page):
    page.set_content("<p>hello</p>")
    result = discover(page, "Nowhere", timeout_ms=300)
    assert result.status == MISSING
    assert "no visible element matches" in result.reason


def test_explicit_locators(page):
    page.set_content('<input id="amount" aria-label="Amount"><div class="total">42</div>')
    assert discover(page, "css=.total").locator.inner_text() == "42"
    assert discover(page, "label=Amount").status == FOUND
    assert discover(page, "id=amount").status == FOUND


def test_grid_cell_finds_the_right_input(page):
    page.set_content(GRID_HTML)
    result = discover(page, "WED cell of Test Project 2")
    assert result.status == FOUND
    assert result.strategy == "grid"
    result.locator.fill("25")
    assert page.evaluate("document.getElementById('w2').value") == "25"
    assert page.evaluate("document.getElementById('w1').value") == ""
    assert page.evaluate("document.getElementById('m2').value") == ""


def test_grid_ambiguous_column_is_refused(page):
    page.set_content("<table><tr><th>WED 14-Oct</th><th>WED 21-Oct</th></tr>"
                     "<tr><td>P</td><td><input></td><td><input></td></tr></table>")
    assert discover(page, "WED cell of P").status == AMBIGUOUS


def test_grid_ambiguous_row_is_refused(page):
    page.set_content("<table><tr><th>WED 14-Oct</th></tr>"
                     "<tr><td>Test Project 2</td><td><input></td></tr>"
                     "<tr><td>Test Project 2</td><td><input></td></tr></table>")
    assert discover(page, "WED cell of Test Project 2").status == AMBIGUOUS


def test_locked_grid_cell_is_still_found(page):
    page.set_content("<table><tr><th>WED 14-Oct</th></tr>"
                     "<tr><td>Test Project 2</td><td><input disabled></td></tr></table>")
    result = discover(page, "WED cell of Test Project 2")
    assert result.status == FOUND
    assert result.locator.is_editable() is False


def test_element_inside_iframe_is_found(page):
    page.set_content("<iframe srcdoc='<button>Inside frame</button>'></iframe>")
    result = discover(page, "Inside frame")
    assert result.status == FOUND
    assert result.frame.parent_frame is not None
    assert result.locator.inner_text() == "Inside frame"