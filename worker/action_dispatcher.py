"""Phase E (part 1): run one plan, or a test's plans in order.

Every operation goes through the Phase 1 registry (permission and signature checks)
and, for element targets, the Phase D discovery (exactly one visible element).
Checks are handed to the assertion engine. A test's plans are all validated before
any of them run, so an unknown step never leaves a half-run test behind.
"""
from core.action_registry import OperationError, lookup
from worker.assertion_engine import evaluate_check
from worker.dom_discovery import AMBIGUOUS, FOUND, discover
from worker.operations import ERROR, NEEDS_REVIEW, PASSED, Outcome, first_line, invoke
NAV_TIMEOUT_MS = 60000


def _absolute(base_url, target):
    if target.lower().startswith("http"):
        return target
    return base_url.rstrip("/") + "/" + target.lstrip("/")


def _wait_for_settled(page, wait_ms=0):
    """Wait for Oracle ADF PPR requests, animations, and busy glass panes to complete."""
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)
    try:
        page.wait_for_function(
            """() => {
                try {
                    if (window.AdfPage && window.AdfPage.PAGE) {
                        if (typeof window.AdfPage.PAGE.isSynchronized === 'function') {
                            return window.AdfPage.PAGE.isSynchronized();
                        }
                    }
                } catch (e) {}
                return true;
            }""",
            timeout=10000,
        )
    except Exception:
        pass
    try:
        page.wait_for_selector(
            ".AFBlockingGlassPane, [id$='::busy'], [id$='::BusyPopup'], [class*='BusyPane'], .af_processingIndicator",
            state="hidden",
            timeout=10000,
        )
    except Exception:
        pass


def _resolve_editable(locator):
    """If locator points to a label or container instead of an input, resolve the associated control."""
    try:
        tag = locator.evaluate("el => el.tagName.toLowerCase()")
        if tag in ("input", "textarea", "select") or locator.evaluate("el => el.isContentEditable"):
            return locator
        target_id = locator.evaluate("el => el.htmlFor || (el.closest('label') && el.closest('label').htmlFor) || ''")
        if target_id:
            candidate = locator.page.locator(f"#{target_id}").filter(visible=True)
            if candidate.count() > 0:
                return candidate.first
        nested = locator.locator("input, textarea, select").filter(visible=True)
        if nested.count() > 0:
            return nested.first
    except Exception:
        pass
    return locator


def execute(page, base_url, plan, timeout_ms=5000):
    """Run one plan and return its Outcome."""
    if not plan.ok:
        return Outcome(NEEDS_REVIEW, reason=plan.reason)
    try:
        owner, name = plan.operation.split(".", 1)
        spec = lookup(owner, name)
    except OperationError as exc:
        return Outcome(NEEDS_REVIEW, reason=str(exc))

    if plan.kind == "check":
        return evaluate_check(page, plan, timeout_ms)

    _wait_for_settled(page, 0)

    try:
        if plan.kind == "navigate":
            invoke(page, spec, value=_absolute(base_url, plan.target),
                   timeout=max(timeout_ms, NAV_TIMEOUT_MS),
                   wait_until="domcontentloaded")
            _wait_for_settled(page, 500)
            return Outcome(PASSED)
        if plan.kind == "key":
            invoke(page.keyboard, spec, value=plan.value)
            return Outcome(PASSED)
        if plan.kind == "wait" and not plan.target:  # a fixed pause
            invoke(page, spec, value=plan.value)
            return Outcome(PASSED)
    except Exception as exc:
        return Outcome(ERROR, reason=first_line(exc))

    found = discover(page, plan.target, timeout_ms)
    if found.status == AMBIGUOUS:
        return Outcome(NEEDS_REVIEW, reason=found.reason)
    if found.status != FOUND:
        return Outcome(ERROR, reason=found.reason)

    options = {"timeout": timeout_ms}
    if plan.expect:  # waits: visible or hidden
        options["state"] = plan.expect

    target_locator = (
        _resolve_editable(found.locator)
        if plan.kind == "action" and spec.name in ("fill", "type", "press_sequentially", "clear")
        else found.locator
    )

    try:
        invoke(target_locator, spec, value=plan.value or None, **options)
        if spec.name == "select_option":
            _wait_for_settled(page, 600)
    except Exception as exc:
        if spec.name == "select_option" and "not a <select> element" in str(exc).lower():
            try:
                target_locator.click(timeout=timeout_ms)
                page.wait_for_timeout(350)
                opt = page.locator(
                    f'[role="option"]:has-text("{plan.value}"), tr:has-text("{plan.value}"), li:has-text("{plan.value}"), [title="{plan.value}" i]'
                ).filter(visible=True).first
                if opt.count() > 0:
                    opt.click(timeout=timeout_ms)
                else:
                    page.get_by_text(plan.value, exact=True).click(timeout=timeout_ms)
                _wait_for_settled(page, 600)
                return Outcome(PASSED)
            except Exception as inner_exc:
                return Outcome(ERROR, reason=f"Custom dropdown select failed: {first_line(inner_exc)}")
        return Outcome(ERROR, reason=first_line(exc))

    if spec.name in ("fill", "type", "press_sequentially") and plan.value:
        page.wait_for_timeout(150)
        try:
            curr = target_locator.input_value()
            if curr != plan.value:
                _wait_for_settled(page, 400)
                refound = discover(page, plan.target, timeout_ms)
                if refound.status == FOUND:
                    re_target = _resolve_editable(refound.locator)
                    re_target.fill(plan.value)
        except Exception:
            pass

    if spec.name == "click" and any(w in plan.target.lower() for w in ("next", "submit", "save", "continue")):
        _wait_for_settled(page, 500)

    return Outcome(PASSED)


def run_plans(page, base_url, plans, timeout_ms=5000, pause_ms=0):
    """Run a test's plans in order. Stops at the first step that does not pass."""
    for number, plan in enumerate(plans, start=1):
        if not plan.ok:
            return Outcome(NEEDS_REVIEW, step=number, reason=plan.reason)

    for number, plan in enumerate(plans, start=1):
        outcome = execute(page, base_url, plan, timeout_ms)
        if outcome.status != PASSED:
            return Outcome(outcome.status, step=number, reason=outcome.reason)
        if pause_ms:
            page.wait_for_timeout(pause_ms)
    return Outcome(PASSED)