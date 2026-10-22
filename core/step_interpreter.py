"""Rule-based step interpreter.

Turns one CSV step into a Plan. It runs nothing and names no Playwright method
in code. Operations are looked up in core/action_registry.py. English verbs,
state words, and key names come from core/verb_aliases.json.

Accepted forms:
  action | target | value                      explicit, uses registry names
  Click the Save button                        plain English, any registry verb
  Enter 25 in the WED cell of Test Project 2   plain English with a value
  Check that Saved is displayed                expectation
  Check that the Hours field has value 25      expectation with a value
  Wait 2 seconds / Wait for Loading to disappear
  Press Enter / Go to /timesheet
"""
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from core.action_registry import OperationError, lookup


def _normalize(text):
    return " ".join(text.lower().replace("-", " ").replace("_", " ").split())


_DATA = json.loads(Path(__file__).with_name("verb_aliases.json").read_text(encoding="utf-8"))
VERBS = {_normalize(k): v for k, v in _DATA["verbs"].items()}
STATES = {_normalize(k): v for k, v in _DATA["states"].items()}
KEYS = {_normalize(k): v for k, v in _DATA["keys"].items()}
ROLE_WORDS = {w.lower() for w in _DATA["role_words"]}

SEARCH_OWNERS = ("locator", "page", "keyboard", "mouse")
# Parameter names that carry a value to type, select, upload, or press.
VALUE_PARAMS = {"value", "values", "text", "files", "key"}

SEPARATOR = re.compile(r"\s+(?:in|into|from|to|as|with)\s+", re.IGNORECASE)
CHECK_LEAD = re.compile(r"^(?:check|verify|confirm)\s+that\b", re.IGNORECASE)
EXPECTATION = re.compile(
    r"^(?:check|verify|confirm)\s+that\s+(?:the\s+)?(?P<target>.+?)\s+"
    r"(?P<pred>is|are|has|have|shows|contains)\s+(?P<rest>.+)$",
    re.IGNORECASE,
)
WAIT_SECONDS = re.compile(
    r"^wait\s+(?:for\s+)?(?P<n>\d+(?:\.\d+)?)\s*(?P<unit>ms|milliseconds?|s|secs?|seconds?)$",
    re.IGNORECASE,
)
WAIT_FOR = re.compile(
    r"^wait\s+for\s+(?P<target>.+?)(?:\s+to\s+(?P<end>appear|be visible|be shown|disappear|be hidden))?$",
    re.IGNORECASE,
)
KEY_PRESS = re.compile(r"^(?:press|hit)\s+(?P<key>.+)$", re.IGNORECASE)


@dataclass(frozen=True)
class Plan:
    step: str
    status: str            # "ok" or "needs_review"
    kind: str = ""         # action, check, key, navigate, wait
    operation: str = ""    # registry operation, "owner.name"
    target: str = ""       # element description or locator, as written
    value: str = ""        # text to type, option, key, or value to compare
    expect: str = ""       # for checks and waits: visible, hidden, value, text, ...
    negate: bool = False   # for checks: the expectation is the opposite
    reason: str = ""       # why the step needs review

    @property
    def ok(self):
        return self.status == "ok"


def _review(step, reason):
    return Plan(step=step, status="needs_review", reason=reason)


def _ok(step, **fields):
    return Plan(step=step, status="ok", **fields)


def _spec(name, owners=SEARCH_OWNERS):
    """Return the permitted registry spec for name, or raise OperationError."""
    blocked = ""
    for owner in owners:
        try:
            return lookup(owner, name)
        except OperationError as exc:
            if "not permitted" in str(exc) and not blocked:
                blocked = str(exc)
    raise OperationError(blocked or f"'{name}' is not a Playwright operation")


def _clean_target(text):
    """Drop a leading article and a trailing role word: 'the Save button' -> 'Save'."""
    words = text.split()
    if words and words[0].lower() in ("the", "a", "an"):
        words = words[1:]
    if len(words) > 1 and words[-1].lower() in ROLE_WORDS:
        words = words[:-1]
    res = " ".join(words)
    if res.startswith("*"):
        res = res.lstrip("* ").strip()
    return res


def _build(step, spec, target, value=""):
    """Turn a permitted registry operation and its arguments into a plan."""
    op = f"{spec.owner}.{spec.name}"

    if spec.owner == "page" and spec.name == "goto":
        if not (target.startswith("/") or target.lower().startswith("http")):
            return _review(step, "'go to' needs a path such as /timesheet or a full URL")
        return _ok(step, kind="navigate", operation=op, target=target)

    if spec.owner == "keyboard":
        key = value or target
        if not key:
            return _review(step, "a key press needs a key name, for example Enter")
        return _ok(step, kind="key", operation=op, value=KEYS.get(_normalize(key), key))

    if not target:
        return _review(step, f"'{spec.name}' needs a target element")

    needs_value = any(
        p in VALUE_PARAMS and p in spec.required_params()
        for p in spec.signature.parameters
    )
    if needs_value and not value:
        return _review(step, f"'{spec.name}' needs a value. Write it as: {spec.name} <value> in <target>")

    kind = "wait" if spec.name.startswith("wait_for") else "action"
    return _ok(step, kind=kind, operation=op, target=target, value=value)


def _state_plan(step, target, state, value, negate):
    """A check on one element state. Every check is a registry read operation."""
    if not target:
        return _review(step, "this check needs a target element")
    if state in ("value", "text") and not value:
        return _review(step, f"the '{state}' check needs a value to compare with")
    name = {"value": "input_value", "text": "inner_text"}.get(state, f"is_{state}")
    try:
        spec = _spec(name)
    except OperationError as exc:
        return _review(step, f"'{state}' is not a known check: {exc}")
    return _ok(step, kind="check", operation=f"{spec.owner}.{spec.name}",
               target=target, value=value, expect=state, negate=negate)


def _resolve_state(word):
    """Map a state phrase to (state, negate). '!' in the alias file means the opposite."""
    key = _normalize(word)
    state = STATES.get(key, key.replace(" ", "_"))
    if state.startswith("!"):
        return state[1:], True
    return state, False


def _interpret_expectation(step, match):
    target = _clean_target(match.group("target"))
    rest = match.group("rest").strip()
    negate = False
    if rest.lower().startswith("not "):
        negate, rest = True, rest[4:].strip()
    value = ""
    if match.group("pred").lower() in ("has", "have", "contains") and rest.lower().startswith("value "):
        rest, value = "value", rest[6:].strip()
    state, flip = _resolve_state(rest)
    return _state_plan(step, target, state, value, negate != flip)


def _plain_action(step, spec, rest):
    value = ""
    target = rest
    if any(p in VALUE_PARAMS for p in spec.signature.parameters):
        if spec.name == "select_option":
            m = re.search(r"\s+from\s+", rest, re.IGNORECASE)
            if m:
                value, target = rest[:m.start()].strip(), rest[m.end():]
            else:
                parts = SEPARATOR.split(rest, maxsplit=1)
                if len(parts) == 2:
                    value, target = parts[0].strip(), parts[1]
        else:
            parts = SEPARATOR.split(rest, maxsplit=1)
            if len(parts) == 2:
                value, target = parts[0].strip(), parts[1]
    if not (spec.owner == "page" and spec.name == "goto"):
        target = _clean_target(target)
    return _build(step, spec, target.strip(), value)


def _interpret_plain_action(step, text):
    """Try the longest leading phrase as a verb, so 'Hover over Help' is hover, not 'over'."""
    words = text.split()
    blocked = ""
    for i in range(len(words), 0, -1):
        verb = " ".join(words[:i])
        rest = " ".join(words[i:])
        name = VERBS.get(_normalize(verb), _normalize(verb).replace(" ", "_"))
        try:
            spec = _spec(name)
        except OperationError as exc:
            if i == 1 and "not permitted" in str(exc):
                blocked = str(exc)
            continue
        return _plain_action(step, spec, rest)
    if blocked:
        return _review(step, blocked)
    return _review(step, "not a recognized instruction. Write it as action | target | value, "
                         "or in a form such as Click the Save button")


def _interpret_wait_seconds(step, match):
    number = float(match.group("n"))
    unit = match.group("unit").lower()
    milliseconds = number if unit.startswith(("ms", "milli")) else number * 1000
    try:
        spec = _spec("wait_for_timeout")
    except OperationError as exc:
        return _review(step, str(exc))
    return _ok(step, kind="wait", operation=f"{spec.owner}.{spec.name}", value=str(int(milliseconds)))


def _interpret_wait_for(step, match):
    target = _clean_target(match.group("target"))
    end = (match.group("end") or "").lower()
    state = "hidden" if end in ("disappear", "be hidden") else "visible"
    if not target:
        return _review(step, "'wait for' needs a target element")
    try:
        spec = _spec("wait_for")
    except OperationError as exc:
        return _review(step, str(exc))
    return _ok(step, kind="wait", operation=f"{spec.owner}.{spec.name}", target=target, expect=state)


def _explicit_expect(step, action, target, value):
    word = _normalize(action[len("expect_"):])
    negate = False
    if word.startswith("not "):
        negate, word = True, word[4:]
    state, flip = _resolve_state(word)
    return _state_plan(step, target, state, value, negate != flip)


def _interpret_explicit(step, text):
    parts = [p.strip() for p in text.split("|", 2)]
    action = _normalize(parts[0]).replace(" ", "_")
    target = parts[1] if len(parts) > 1 else ""
    value = parts[2] if len(parts) > 2 else ""

    if action.startswith("expect_"):
        return _explicit_expect(step, action, target, value)
    if action == "press" and _normalize(target) in KEYS:
        return _build(step, _spec("press", owners=("keyboard",)), "", KEYS[_normalize(target)])
    try:
        spec = _spec(action)
    except OperationError as exc:
        return _review(step, str(exc))
    return _build(step, spec, target, value)


def interpret(step):
    """Return a Plan for one step. Never executes anything."""
    text = " ".join(step.split())
    if not text:
        return _review(step, "step is empty")
    if "|" in text:
        return _interpret_explicit(step, text)
    if CHECK_LEAD.match(text):
        match = EXPECTATION.match(text)
        if not match:
            return _review(step, "not a recognized check. Write it as Check that <target> is <state>, "
                                 "for example Check that Saved is displayed")
        return _interpret_expectation(step, match)
    match = WAIT_SECONDS.match(text)
    if match:
        return _interpret_wait_seconds(step, match)
    match = WAIT_FOR.match(text)
    if match:
        return _interpret_wait_for(step, match)
    match = KEY_PRESS.match(text)
    if match and _normalize(match.group("key")) in KEYS:
        return _ok(step, kind="key", operation="keyboard.press", value=KEYS[_normalize(match.group("key"))])
    return _interpret_plain_action(step, text)


def interpret_steps(steps_text):
    """Interpret a whole steps cell, split on semicolons."""
    return [interpret(s.strip()) for s in steps_text.split(";") if s.strip()]


if __name__ == "__main__":
    for step_text in sys.argv[1:]:
        print(interpret(step_text))