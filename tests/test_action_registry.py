import pytest

from core.action_registry import OperationError, categorize, check_call, lookup, registry


def test_discovers_standard_operations():
    ops = registry()
    assert ("locator", "click") in ops
    assert ("page", "goto") in ops
    assert ("keyboard", "press") in ops


def test_common_interactions_are_allowed():
    for owner, name in [("locator", "click"), ("locator", "hover"), ("locator", "fill"),
                        ("page", "goto"), ("keyboard", "press")]:
        assert lookup(owner, name).allowed


@pytest.mark.parametrize("owner, name", [
    ("locator", "evaluate"),
    ("locator", "evaluate_handle"),
    ("page", "evaluate"),
    ("page", "route"),
    ("page", "expose_function"),
    ("page", "add_init_script"),
    ("page", "close"),
    ("page", "set_content"),
    ("page", "screenshot"),
])
def test_blocked_operations_are_refused(owner, name):
    with pytest.raises(OperationError, match="not permitted"):
        lookup(owner, name)


def test_file_upload_is_off_by_default():
    with pytest.raises(OperationError, match="reads local files"):
        lookup("locator", "set_input_files")


def test_no_blocked_category_is_allowed():
    for spec in registry().values():
        if spec.category == "blocked":
            assert not spec.allowed, spec.name


def test_no_private_names_are_allowed():
    for spec in registry().values():
        if spec.allowed:
            assert not spec.name.startswith("_")


def test_required_arguments_come_from_signature():
    fill = registry()[("locator", "fill")]
    assert "value" in fill.required_params()
    hover = registry()[("locator", "hover")]
    assert hover.required_params() == []


def test_unknown_operation_is_refused():
    with pytest.raises(OperationError, match="not a Playwright operation"):
        lookup("locator", "teleport")


def test_wrong_arguments_are_refused():
    with pytest.raises(OperationError):
        check_call("locator", "fill", args=())          # fill needs a value
    check_call("locator", "fill", args=("25",))         # valid


def test_categories_are_stable():
    assert categorize("click") == "interaction"
    assert categorize("is_visible") == "inspection"
    assert categorize("wait_for") == "wait"
    assert categorize("evaluate") == "blocked"

def test_factories_are_not_actions():
    assert categorize("get_by_role") == "factory"
    assert categorize("locator") == "factory"
    for owner, name in [("locator", "get_by_text"), ("page", "get_by_role")]:
        with pytest.raises(OperationError, match="not permitted"):
            lookup(owner, name)


def test_dom_handles_and_listeners_are_blocked():
    for name in ["element_handle", "query_selector", "eval_on_selector", "on", "expect_event"]:
        assert categorize(name) == "blocked", name