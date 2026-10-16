import pytest

from core import step_interpreter as si
from core.step_interpreter import interpret, interpret_steps


def test_longest_verb_wins():
    plan = interpret("Hover over Help")
    assert plan.ok and plan.operation == "locator.hover" and plan.target == "Help"


@pytest.mark.parametrize("step, operation, target", [
    ("Click the Save button", "locator.click", "Save"),
    ("Click Save", "locator.click", "Save"),
    ("Tap the Next Week button", "locator.click", "Next Week"),
    ("Press Save", "locator.click", "Save"),
    ("Double-click Test Project 2", "locator.dblclick", "Test Project 2"),
    ("Check the Remember me box", "locator.check", "Remember me"),
])
def test_plain_actions(step, operation, target):
    plan = interpret(step)
    assert plan.ok, plan.reason
    assert (plan.kind, plan.operation, plan.target) == ("action", operation, target)


@pytest.mark.parametrize("step, target, value", [
    ("Enter 25 in the WED cell of Test Project 2", "WED cell of Test Project 2", "25"),
    ("Type Test into the Search field", "Search", "Test"),
    ("Type Ann in Username", "Username", "Ann"),
])
def test_fill_plain(step, target, value):
    plan = interpret(step)
    assert plan.ok, plan.reason
    assert (plan.operation, plan.target, plan.value) == ("locator.fill", target, value)


def test_select_option_plain():
    plan = interpret("Select Yes from the Approved list")
    assert plan.ok
    assert (plan.operation, plan.target, plan.value) == ("locator.select_option", "Approved", "Yes")


@pytest.mark.parametrize("step, operation, target, expect, negate", [
    ("Check that Saved is displayed", "locator.is_visible", "Saved", "visible", False),
    ("Check that Error is not displayed", "locator.is_visible", "Error", "visible", True),
    ("Check that the Save button is enabled", "locator.is_enabled", "Save", "enabled", False),
    ("Check that the Save button is disabled", "locator.is_disabled", "Save", "disabled", False),
    ("Check that the WED cell of Test Project 2 is not editable",
     "locator.is_editable", "WED cell of Test Project 2", "editable", True),
    ("Check that the Remember me box is read only", "locator.is_editable", "Remember me", "editable", True),
    ("Check that the Remember me box is checked", "locator.is_checked", "Remember me", "checked", False),
    ("Check that the Remember me box is unchecked", "locator.is_checked", "Remember me", "checked", True),
])
def test_checks_plain(step, operation, target, expect, negate):
    plan = interpret(step)
    assert plan.ok, plan.reason
    assert plan.kind == "check"
    assert (plan.operation, plan.target, plan.expect, plan.negate) == (operation, target, expect, negate)


def test_value_check_plain():
    plan = interpret("Check that the Hours field has value 25")
    assert plan.ok
    assert (plan.operation, plan.target, plan.value, plan.expect) == \
        ("locator.input_value", "Hours", "25", "value")


def test_check_without_recognized_shape_is_not_guessed():
    plan = interpret("Check that Saved")
    assert plan.status == "needs_review"
    assert "not a recognized check" in plan.reason


def test_press_key_names():
    plan = interpret("Press Enter")
    assert (plan.kind, plan.operation, plan.value) == ("key", "keyboard.press", "Enter")
    assert interpret("Press page down").value == "PageDown"


def test_press_word_that_is_not_a_key_is_a_click():
    plan = interpret("Press End Date")
    assert plan.ok and plan.operation == "locator.click" and plan.target == "End Date"


def test_navigation():
    plan = interpret("Go to /timesheet")
    assert (plan.kind, plan.operation, plan.target) == ("navigate", "page.goto", "/timesheet")
    assert interpret("Go to Settings").status == "needs_review"


def test_waits():
    seconds = interpret("Wait 2 seconds")
    assert (seconds.operation, seconds.value) == ("page.wait_for_timeout", "2000")
    appear = interpret("Wait for Loading to appear")
    assert (appear.operation, appear.target, appear.expect) == ("locator.wait_for", "Loading", "visible")
    gone = interpret("Wait for Loading to disappear")
    assert gone.expect == "hidden"


def test_operation_without_alias_resolves_from_registry():
    # No alias for "drag and drop" exists. The registry supplies the operation.
    plan = interpret("Drag and drop Save to Trash")
    assert plan.ok, plan.reason
    assert plan.operation.endswith("drag_and_drop")


def test_new_verb_needs_only_an_alias_line(monkeypatch):
    monkeypatch.setitem(si.VERBS, "dbl tap", "dblclick")
    plan = interpret("Dbl tap Save")
    assert plan.ok and plan.operation == "locator.dblclick" and plan.target == "Save"


def test_file_upload_is_refused_by_policy():
    plan = interpret("Upload sample.csv to the File field")
    assert plan.status == "needs_review"
    assert "reads local files" in plan.reason


def test_blocked_verb_is_refused():
    plan = interpret("Evaluate Save")
    assert plan.status == "needs_review"
    assert "not permitted" in plan.reason


def test_unknown_sentence_needs_review():
    plan = interpret("Teleport to the moon")
    assert plan.status == "needs_review"
    assert "not a recognized instruction" in plan.reason


@pytest.mark.parametrize("step, operation, value", [
    ("fill | label=Username | Ann", "locator.fill", "Ann"),
    ("press | Tab", "keyboard.press", "Tab"),
    ("goto | /login", "page.goto", ""),
])
def test_explicit_form_uses_registry(step, operation, value):
    plan = interpret(step)
    assert plan.ok, plan.reason
    assert (plan.operation, plan.value) == (operation, value)


def test_explicit_expectations():
    visible = interpret("expect_visible | text=Help")
    assert (visible.operation, visible.expect, visible.negate) == ("locator.is_visible", "visible", False)
    value = interpret("expect_value | label=Hours | 25")
    assert (value.operation, value.value, value.expect) == ("locator.input_value", "25", "value")
    hidden = interpret("expect_not_visible | text=Error")
    assert (hidden.operation, hidden.negate) == ("locator.is_visible", True)


def test_explicit_unknown_action_needs_review():
    plan = interpret("teleport | text=Help")
    assert plan.status == "needs_review"
    assert "not a Playwright operation" in plan.reason


def test_explicit_blocked_action_needs_review():
    plan = interpret("evaluate | text=Help | 1")
    assert plan.status == "needs_review"
    assert "not permitted" in plan.reason


def test_explicit_missing_value_needs_review():
    assert "needs a value" in interpret("fill | label=Username").reason
    assert "needs a value" in interpret("expect_value | label=Hours").reason


def test_steps_cell_is_split():
    plans = interpret_steps("Click Save; Check that Saved is displayed; teleport | text=X")
    assert [p.status for p in plans] == ["ok", "ok", "needs_review"]