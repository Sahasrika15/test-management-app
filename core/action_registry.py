"""Dynamic registry of Playwright operations.

Methods are discovered by introspecting the installed Playwright classes.
A written policy decides which discovered methods may run. Discovery alone
never grants permission.
"""
import inspect
from dataclasses import dataclass
from functools import lru_cache
from importlib.metadata import version as package_version

from playwright import sync_api

TARGETS = {
    "locator": sync_api.Locator,
    "page": sync_api.Page,
    "frame": sync_api.Frame,
    "keyboard": sync_api.Keyboard,
    "mouse": sync_api.Mouse,
}

# ---- Policy: written by a person. Introspection only supplies the candidates. ----

BLOCKED_NAMES = {
    # run JavaScript or expose DOM handles
    "wait_for_function", "eval_on_selector", "eval_on_selector_all",
    "element_handle", "element_handles", "query_selector", "query_selector_all",
    "frame_element",
    # replace or control the page or environment
    "set_content", "pause", "close", "emulate_media", "request_gc",
    "opener", "pick_locator", "cancel_pick_locator",
    # write files or export secrets
    "screenshot", "pdf", "storage_state", "set_extra_http_headers", "set_geolocation",
    # attach Python callbacks or listeners
    "on", "once", "remove_listener", "remove_locator_handler",
}
BLOCKED_PREFIXES = ("evaluate", "expose_", "route", "unroute", "add_", "expect_", "_")

# Reads local files from the worker's disk, so it is off until explicitly enabled.
ON_REQUEST_ONLY = {"set_input_files", "drop"}

# Return a locator and do nothing else. The dispatcher refuses them.
FACTORY_NAMES = {"locator", "frame_locator", "filter", "and_", "or_", "nth", "within",
                 "all", "normalize"}
FACTORY_PREFIXES = ("get_by_",)

# Interaction operations change the page.
INTERACTION = {
    "click", "dblclick", "hover", "fill", "type", "press", "press_sequentially",
    "check", "uncheck", "set_checked", "select_option", "select_text", "tap",
    "drag_to", "drag_and_drop", "focus", "blur", "clear", "dispatch_event",
    "scroll_into_view_if_needed", "insert_text", "down", "up", "move", "wheel",
}

NAVIGATION = {"goto", "reload", "go_back", "go_forward"}

INSPECTION_NAMES = {"aria_snapshot", "console_messages", "page_errors", "requests"}
INSPECTION_PREFIXES = ("get_", "is_", "inner_", "input_value", "text_content",
                       "count", "bounding_box", "content", "title", "all_")
WAIT_PREFIX = "wait_for"

ALLOWED_CATEGORIES = {"interaction", "navigation", "inspection", "wait"}


def categorize(name):
    if name in BLOCKED_NAMES or name.startswith(BLOCKED_PREFIXES):
        return "blocked"
    if name in ON_REQUEST_ONLY:
        return "on_request"
    if name in FACTORY_NAMES or name.startswith(FACTORY_PREFIXES):
        return "factory"
    if name in INTERACTION:
        return "interaction"
    if name in NAVIGATION:
        return "navigation"
    if name.startswith(WAIT_PREFIX):
        return "wait"
    if name in INSPECTION_NAMES or name.startswith(INSPECTION_PREFIXES):
        return "inspection"
    return "unclassified"


class OperationError(Exception):
    """Raised when an operation is unknown, not permitted, or called incorrectly."""


@dataclass(frozen=True)
class OperationSpec:
    owner: str
    name: str
    category: str
    allowed: bool
    reason: str
    signature: inspect.Signature  # parameters without self

    def required_params(self):
        return [p.name for p in self.signature.parameters.values()
                if p.default is inspect.Parameter.empty
                and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]

    def optional_params(self):
        required = self.required_params()
        return [p.name for p in self.signature.parameters.values() if p.name not in required]


@lru_cache(maxsize=4)
def _build(playwright_version):
    """Build the registry once per installed Playwright version."""
    ops = {}
    for owner, cls in TARGETS.items():
        for name in dir(cls):
            if name.startswith("_"):
                continue
            static = inspect.getattr_static(cls, name, None)
            if not inspect.isfunction(static):  # skips properties such as .page and .context
                continue
            sig = inspect.signature(static)
            sig = sig.replace(parameters=list(sig.parameters.values())[1:])  # drop self
            category = categorize(name)
            allowed = category in ALLOWED_CATEGORIES
            if allowed:
                reason = ""
            elif category == "blocked":
                reason = "blocked by safety policy"
            elif category == "on_request":
                reason = "reads local files; enable explicitly to use"
            else:
                reason = f"category '{category}' is not enabled"
            ops[(owner, name)] = OperationSpec(owner, name, category, allowed, reason, sig)
    return ops


def registry():
    """Return {(owner, name): OperationSpec} for the installed Playwright."""
    return _build(package_version("playwright"))


def lookup(owner, name):
    spec = registry().get((owner, name))
    if spec is None:
        raise OperationError(f"{owner}.{name} is not a Playwright operation")
    if not spec.allowed:
        raise OperationError(f"{owner}.{name} is not permitted: {spec.reason}")
    return spec


def check_call(owner, name, args=(), kwargs=None):
    """Confirm the operation is permitted and the arguments fit its signature."""
    spec = lookup(owner, name)
    try:
        spec.signature.bind(*args, **(kwargs or {}))
    except TypeError as exc:
        raise OperationError(f"{owner}.{name}: {exc}") from exc
    return spec


if __name__ == "__main__":
    ops = registry()
    counts = {}
    for spec in ops.values():
        counts[spec.category] = counts.get(spec.category, 0) + 1
    print(f"Playwright {package_version('playwright')}: {len(ops)} operations discovered")
    for category, n in sorted(counts.items()):
        print(f"  {category}: {n}")
    for owner in TARGETS:
        allowed = sorted(s.name for s in ops.values() if s.owner == owner and s.allowed)
        print(f"\n{owner} allowed ({len(allowed)}): {', '.join(allowed)}")