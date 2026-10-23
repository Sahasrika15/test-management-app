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

# JS expression that, given a DOM element, walks the surrounding structure to find
# the closest editable <input> or <textarea>.  It handles:
#   - Standard inputs and textareas (returned as-is).
#   - ADF LOV / combobox fields where discovery lands on an icon <a> whose id ends
#     with "::lovIconId" or "::popup" — the real input is the sibling with "::content".
#   - label[for=…] → the associated control.
#   - Any input/textarea that lives inside the same immediate container (up to 4 hops).
_JS_FIND_EDITABLE = """
el => {
    const isInput = n =>
        n &&
        ['input', 'textarea'].includes(n.tagName.toLowerCase()) &&
        n.type !== 'hidden' &&
        !n.disabled;
    const isCE = n => n && n.isContentEditable;

    // Already an editable input / textarea / contenteditable.
    if (isInput(el) || isCE(el)) return { type: 'self' };

    // ADF pattern: id ends with ::lovIconId or similar – sibling ::content exists.
    if (el.id && el.id.includes('::')) {
        const base = el.id.substring(0, el.id.lastIndexOf('::'));
        const byContent = document.getElementById(base + '::content')
                       || document.querySelector('[id^="' + base + '"][id$="::content"]');
        if (byContent && isInput(byContent)) {
            return { type: 'attr', attr: 'id', value: byContent.id };
        }
    }

    // label[for=…]
    const labelFor = el.htmlFor || (el.closest('label') && el.closest('label').htmlFor);
    if (labelFor) {
        const target = document.getElementById(labelFor);
        if (target && (isInput(target) || isCE(target))) {
            return { type: 'attr', attr: 'id', value: target.id };
        }
    }

    // Descend into children first.
    const childInp = el.querySelector(
        'input:not([type="hidden"]):not([disabled]), textarea:not([disabled])'
    );
    if (childInp && isInput(childInp)) {
        return childInp.id
            ? { type: 'attr', attr: 'id', value: childInp.id }
            : (childInp.setAttribute('data-verity-editable',
               'v' + Math.random().toString(36).slice(2, 9)),
               { type: 'attr', attr: 'data-verity-editable',
                 value: childInp.getAttribute('data-verity-editable') });
    }

    // Walk upward (max 4 hops) looking for a sibling or cousin input.
    let container = el.parentElement;
    for (let depth = 0; depth < 4 && container; depth++) {
        const inp = container.querySelector(
            'input:not([type="hidden"]):not([disabled]), textarea:not([disabled])'
        );
        if (inp && isInput(inp)) {
            return inp.id
                ? { type: 'attr', attr: 'id', value: inp.id }
                : (inp.setAttribute('data-verity-editable',
                   'v' + Math.random().toString(36).slice(2, 9)),
                   { type: 'attr', attr: 'data-verity-editable',
                     value: inp.getAttribute('data-verity-editable') });
        }
        container = container.parentElement;
    }
    return null;
}
"""


def _wait_for_settled(page, wait_ms=0):
    """Wait for Oracle ADF PPR requests, animations, and busy glass panes to complete."""
    if wait_ms > 0:
        page.wait_for_timeout(wait_ms)
    try:
        page.wait_for_selector(
            ".AFBlockingGlassPane, [id$='::busy'], [id$='::BusyPopup'], [class*='BusyPane'], .af_processingIndicator",
            state="hidden",
            timeout=15000,
        )
    except Exception:
        pass
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
            timeout=15000,
        )
    except Exception:
        pass
    if wait_ms > 0:
        page.wait_for_timeout(min(wait_ms, 500))


def _resolve_editable(page, locator):
    """Return the editable <input>/<textarea>/[contenteditable] nearest to *locator*.

    Runs a single JS evaluation that understands:
    - Plain inputs/textareas — returned as-is.
    - Oracle ADF LOV fields whose icon element carries "::lovIconId" in its id;
      the companion "::content" input is resolved without hardcoding field names.
    - label[for=…] associations.
    - Inputs that are siblings or cousins within a 4-hop parent walk.

    Falls back to the original locator so existing behaviour is never worse.
    """
    try:
        result = locator.evaluate(_JS_FIND_EDITABLE)
        if result is None:
            return locator
        if result.get("type") == "self":
            return locator
        attr = result.get("attr", "id")
        value = result.get("value", "")
        if not value:
            return locator
        candidate = page.locator(f'[{attr}="{value}"]').filter(visible=True)
        if candidate.count() == 1:
            return candidate.first
    except Exception:
        pass
    return locator


def _type_into(locator, page, value, delay_ms, post_pause_ms, timeout_ms):
    """Click the element, clear it, type character-by-character, then verify.

    Strategy:
    1. click() to focus and trigger ADF's input listeners.
    2. triple-click to select-all, then press_sequentially to overwrite.
    3. Read back the value; if it doesn't match, attempt a fill() fallback.
    4. Pause for *post_pause_ms* so the application can react (e.g. LOV search).

    Returns an Outcome or None when the element accepted the value.
    """
    try:
        locator.click(timeout=timeout_ms)
        # Select-all so characters replace any pre-filled value.
        locator.page.keyboard.press("Control+a")
        locator.press_sequentially(value, delay=delay_ms, timeout=timeout_ms)
    except Exception as exc:
        return Outcome(ERROR, reason=f"Typing failed: {first_line(exc)}")

    # Verify the value was accepted.
    page.wait_for_timeout(200)
    try:
        current = locator.input_value()
        if current != value:
            # One fallback attempt with fill().
            try:
                locator.fill(value, timeout=timeout_ms)
                page.wait_for_timeout(100)
                current = locator.input_value()
            except Exception:
                pass
            if current != value:
                return Outcome(
                    ERROR,
                    reason=(
                        f"Value not entered: expected {value!r}, "
                        f"field still shows {current!r}"
                    ),
                )
    except Exception:
        pass  # input_value() fails on contenteditable; accept and move on.

    page.wait_for_timeout(post_pause_ms)
    return None  # success


def execute(page, base_url, plan, timeout_ms=5000,
            typing_delay_ms=150, post_fill_pause_ms=1000):
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
        if plan.kind == "wait" and plan.expect == "visible" and found.count > 0:
            return Outcome(PASSED)
        return Outcome(NEEDS_REVIEW, reason=found.reason)
    if found.status != FOUND:
        return Outcome(ERROR, reason=found.reason)

    options = {"timeout": timeout_ms}
    if plan.expect:  # waits: visible or hidden
        options["state"] = plan.expect

    # --- Fill / type operations: resolve to actual editable control and type. ---
    is_fill = plan.kind == "action" and spec.name in (
        "fill", "type", "press_sequentially", "clear"
    )
    if is_fill and plan.value:
        editable = _resolve_editable(page, found.locator)
        err = _type_into(
            editable, page, plan.value,
            delay_ms=typing_delay_ms,
            post_pause_ms=post_fill_pause_ms,
            timeout_ms=timeout_ms,
        )
        if err is not None:
            return err
        if spec.name == "click" and any(
            w in plan.target.lower() for w in ("next", "submit", "save", "continue")
        ):
            _wait_for_settled(page, 500)
        return Outcome(PASSED)

    # --- All other actions (click, select_option, scroll, wait, …). ---
    target_locator = found.locator

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
                    f'[role="option"]:has-text("{plan.value}"), '
                    f'tr:has-text("{plan.value}"), '
                    f'li:has-text("{plan.value}"), '
                    f'[title="{plan.value}" i]'
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

    if spec.name == "click" and any(
        w in plan.target.lower() for w in ("next", "submit", "save", "continue")
    ):
        page.wait_for_timeout(800)
        _wait_for_settled(page, 1000)

    return Outcome(PASSED)


def _absolute(base_url, target):
    if target.lower().startswith("http"):
        return target
    return base_url.rstrip("/") + "/" + target.lstrip("/")


def run_plans(page, base_url, plans, timeout_ms=5000, pause_ms=0,
              typing_delay_ms=150, post_fill_pause_ms=1000):
    """Run a test's plans in order.  Stops at the first step that does not pass."""
    for number, plan in enumerate(plans, start=1):
        if not plan.ok:
            return Outcome(NEEDS_REVIEW, step=number, reason=plan.reason)

    for number, plan in enumerate(plans, start=1):
        outcome = execute(
            page, base_url, plan, timeout_ms,
            typing_delay_ms=typing_delay_ms,
            post_fill_pause_ms=post_fill_pause_ms,
        )
        if outcome.status != PASSED:
            return Outcome(outcome.status, step=number, reason=outcome.reason)
        if pause_ms:
            page.wait_for_timeout(pause_ms)
    return Outcome(PASSED)

    return Outcome(PASSED)