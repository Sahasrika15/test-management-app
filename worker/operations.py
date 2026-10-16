"""Shared pieces for Phase E: statuses, the Outcome record, and the one generic
invoker. Kept separate so the dispatcher and the assertion engine can both use
them without importing each other."""
from dataclasses import dataclass

from core.action_registry import check_call

PASSED = "passed"
FAILED = "failed"
ERROR = "error"
NEEDS_REVIEW = "needs_review"

# Parameter names that carry a value to type, select, navigate to, or press.
VALUE_NAMES = ("value", "text", "key", "url", "values", "files")


@dataclass(frozen=True)
class Outcome:
    status: str
    step: int = 0
    reason: str = ""

    @property
    def passed(self):
        return self.status == PASSED


def first_line(error):
    lines = str(error).strip().splitlines()
    return lines[0] if lines else error.__class__.__name__


def _value_arguments(spec, value):
    """Place the value where this method's signature expects it. No per-method code."""
    required = spec.required_params()
    if required:
        if required[0] == "timeout":
            return [int(value)], {}
        return [value], {}
    for name in VALUE_NAMES:
        if name in spec.signature.parameters:
            return [], {name: value}
    raise ValueError(f"{spec.owner}.{spec.name} does not take a value")


def invoke(obj, spec, value=None, **options):
    """Call a registry-approved operation. Arguments are checked against its real signature.
    Options such as timeout or state are passed only if the method accepts them."""
    args, kwargs = [], {}
    if value is not None:
        args, kwargs = _value_arguments(spec, value)
    kwargs.update({k: v for k, v in options.items() if k in spec.signature.parameters})
    check_call(spec.owner, spec.name, args, kwargs)
    return getattr(obj, spec.name)(*args, **kwargs)