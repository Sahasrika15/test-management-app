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


def _absolute(base_url, target):
    if target.lower().startswith("http"):
        return target
    return base_url.rstrip("/") + "/" + target.lstrip("/")


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

    try:
        if plan.kind == "navigate":
            invoke(page, spec, value=_absolute(base_url, plan.target), timeout=timeout_ms)
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
    try:
        invoke(found.locator, spec, value=plan.value or None, **options)
    except Exception as exc:
        return Outcome(ERROR, reason=first_line(exc))
    return Outcome(PASSED)


def run_plans(page, base_url, plans, timeout_ms=5000):
    """Run a test's plans in order. Stops at the first step that does not pass."""
    for number, plan in enumerate(plans, start=1):
        if not plan.ok:
            return Outcome(NEEDS_REVIEW, step=number, reason=plan.reason)

    for number, plan in enumerate(plans, start=1):
        outcome = execute(page, base_url, plan, timeout_ms)
        if outcome.status != PASSED:
            return Outcome(outcome.status, step=number, reason=outcome.reason)
    return Outcome(PASSED)