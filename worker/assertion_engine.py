"""Phase E (part 2): verify the observed page state for check plans.

A check never assumes an earlier action worked. It reads the element's real state,
polls until the expectation holds or the timeout ends, and reports PASSED or FAILED
with what was observed. An ambiguous target is never checked.
"""
import time

from core.action_registry import OperationError, lookup
from worker.dom_discovery import AMBIGUOUS, FOUND, discover
from worker.operations import ERROR, FAILED, NEEDS_REVIEW, PASSED, Outcome, first_line, invoke

# A missing element still answers "visible" and "hidden" truthfully.
ABSENT_READS = {"is_visible": False, "is_hidden": True}
TEXT_READS = {"input_value", "inner_text"}
POLL_MS = 200


def _satisfied(plan, spec, observed):
    if spec.name in TEXT_READS:
        if plan.expect == "value":
            return str(observed).strip() == plan.value
        return plan.value in str(observed)
    return bool(observed) == (not plan.negate)


def _describe(plan, spec, observed):
    if spec.name in TEXT_READS:
        if plan.expect == "value":
            return f"value of '{plan.target}' is '{observed}', expected '{plan.value}'"
        return f"text of '{plan.target}' does not contain '{plan.value}'"
    expected = ("not " if plan.negate else "") + plan.expect
    return f"'{plan.target}' expected {expected}; observed {bool(observed)}"


def _observe(spec, found, timeout_ms):
    if found.status == FOUND:
        return invoke(found.locator, spec, timeout=timeout_ms)
    if spec.name in ABSENT_READS:
        return ABSENT_READS[spec.name]
    raise LookupError(found.reason)


def evaluate_check(page, plan, timeout_ms=5000):
    """Return PASSED, FAILED (page disagrees), ERROR (could not read), or NEEDS_REVIEW."""
    try:
        spec = lookup(*plan.operation.split(".", 1))
    except OperationError as exc:
        return Outcome(NEEDS_REVIEW, reason=str(exc))

    deadline = time.time() + timeout_ms / 1000
    reason, read_ok = "", False
    while True:
        found = discover(page, plan.target, timeout_ms=0)
        if found.status == AMBIGUOUS:
            return Outcome(NEEDS_REVIEW, reason=found.reason)
        try:
            observed = _observe(spec, found, timeout_ms)
        except LookupError as exc:
            reason = str(exc)
        except Exception as exc:
            reason = first_line(exc)
        else:
            read_ok = True
            if _satisfied(plan, spec, observed):
                return Outcome(PASSED)
            reason = _describe(plan, spec, observed)
        if time.time() >= deadline:
            break
        page.wait_for_timeout(POLL_MS)
    return Outcome(FAILED if read_ok else ERROR, reason=reason)