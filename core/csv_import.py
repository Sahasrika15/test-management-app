import csv
import io
import re
from dataclasses import dataclass, field

REQUIRED_COLUMNS = ["test_case_id", "test_case_name", "page", "steps", "expected_result", "enabled"]

STEP_PATTERNS = [
    ("open_page", re.compile(r"^Open the page$")),
    ("click", re.compile(r"^Click the (?P<name>.+) button$")),
    ("enter", re.compile(r"^Enter (?P<value>.+) in the (?P<field>.+) field$")),
    ("select", re.compile(r"^Select (?P<value>.+) from the (?P<field>.+) list$")),
    ("check_text", re.compile(r"^Check that (?P<text>.+) is displayed$")),
    ("wait_for", re.compile(r"^Wait for (?P<text>.+)$")),
        ("cell", re.compile(r"^Enter (?P<value>.+) in the (?P<day>MON|TUE|WED|THU|FRI|SAT|SUN) cell of (?P<row>.+)$")),
]


@dataclass
class ParseResult:
    rows: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors


def match_step(text):
    for action, pattern in STEP_PATTERNS:
        match = pattern.match(text)
        if match:
            return {"action": action, **match.groupdict()}
    return None


def validate_csv_text(content):
    result = ParseResult()
    reader = csv.DictReader(io.StringIO(content))

    header = reader.fieldnames or []
    missing = [col for col in REQUIRED_COLUMNS if col not in header]
    if missing:
        result.errors.append("Header is missing: " + ", ".join(missing))
        return result

    seen_ids = set()
    for row in reader:
        line = reader.line_num
        errors = []

        test_case_id = (row.get("test_case_id") or "").strip()
        name = (row.get("test_case_name") or "").strip()
        page = (row.get("page") or "").strip()
        steps_text = (row.get("steps") or "").strip()
        expected = (row.get("expected_result") or "").strip()
        enabled_text = (row.get("enabled") or "").strip().lower()

        if not test_case_id:
            errors.append("test_case_id is empty")
        elif test_case_id in seen_ids:
            errors.append(f"test_case_id '{test_case_id}' is used more than once")
        if not name:
            errors.append("test_case_name is empty")
        if not page.startswith("/"):
            errors.append("page must start with / (for example /timesheet)")
        if enabled_text not in ("yes", "no"):
            errors.append("enabled must be Yes or No")
        if not expected:
            errors.append("expected_result is empty")

        steps = [s.strip() for s in steps_text.split(";") if s.strip()]
        if not steps:
            errors.append("steps are empty")
        for step in steps:
            if match_step(step) is None:
                errors.append(f"step '{step}' is not a known pattern")

        if errors:
            result.errors.extend(f"Line {line}: {message}" for message in errors)
            continue

        seen_ids.add(test_case_id)
        result.rows.append({
            "test_case_id": test_case_id,
            "test_case_name": name,
            "page": page,
            "steps": "; ".join(steps),
            "expected_result": expected,
            "enabled": enabled_text == "yes",
        })

    return result