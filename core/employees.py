import csv
import io
import json
import os
import re

from sqlalchemy import text

from db.connection import get_engine

EMPLOYEE_COLUMNS = [
    "first_name", "last_name", "date_of_birth", "address", "zip",
    "state", "city", "county", "business_unit",
]
MAX_BATCH = 50
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{4}$")
PLACEHOLDER = re.compile(r"\$\{(\w+)\}")


def validate_employee_csv(content):
    """Check an employee CSV. Returns (rows, errors). Nothing is saved here."""
    reader = csv.DictReader(io.StringIO(content))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in EMPLOYEE_COLUMNS if c not in header]
    if missing:
        return [], ["Header is missing: " + ", ".join(missing)]

    rows, errors = [], []
    for row in reader:
        line = reader.line_num
        values = {c: (row.get(c) or "").strip() for c in EMPLOYEE_COLUMNS}
        problems = [f"{c} is empty" for c, v in values.items() if not v]
        if values["date_of_birth"] and not DATE_RE.match(values["date_of_birth"]):
            problems.append("date_of_birth must look like 01/01/1990")
        problems += [f"{c} must not contain a semicolon" for c, v in values.items() if ";" in v]
        if problems:
            errors += [f"Line {line}: {p}" for p in problems]
        else:
            rows.append(values)

    if not rows and not errors:
        errors.append("The file has no employee rows")
    if len(rows) > MAX_BATCH:
        errors.append(f"A batch can hold at most {MAX_BATCH} people; this file has {len(rows)}")
    return rows, errors


def save_batch(name, rows):
    with get_engine().begin() as conn:
        batch_id = conn.execute(text("""
            insert into employee_batches (name, total) values (:name, :total) returning id
        """), {"name": name, "total": len(rows)}).scalar_one()
        for number, values in enumerate(rows, start=1):
            conn.execute(text("""
                insert into employee_rows (batch_id, row_no, data)
                values (:batch, :no, cast(:data as jsonb))
            """), {"batch": batch_id, "no": number, "data": json.dumps(values)})
    return batch_id


def list_batches():
    with get_engine().connect() as conn:
        return [dict(r) for r in conn.execute(text(
            "select id, name, total, created_at from employee_batches order by id desc"
        )).mappings()]


def fill(template_text, person):
    def swap(match):
        key = match.group(1)
        if key not in person:
            raise ValueError(f"The test uses ${{{key}}}, which is not a column in the employee file")
        return person[key]
    return PLACEHOLDER.sub(swap, template_text)


def expand_batch(batch_id, template_id):
    """Create one test case per person from the template. Returns the new test case IDs.
    Nothing runs here; the run starts later from Start run."""
    with get_engine().begin() as conn:
        template = conn.execute(text("""
            select test_case_id, test_case_name, page, steps, expected_result
            from test_cases where test_case_id = :tid
        """), {"tid": template_id}).mappings().first()
        if template is None:
            raise ValueError(f"Test case {template_id} does not exist")
        people = conn.execute(text("""
            select row_no, data from employee_rows where batch_id = :b order by row_no
        """), {"b": batch_id}).mappings().all()
        if not people:
            raise ValueError(f"Batch {batch_id} has no people")

        generated = []
        for person in people:
            data = person["data"]
            new_id = f"{template_id}-E{person['row_no']:03d}"
            name = f"{template['test_case_name']} - {data['first_name']} {data['last_name']}"
            conn.execute(text("""
                insert into test_cases
                    (test_case_id, test_case_name, page, steps, expected_result, enabled, source_file)
                values (:id, :name, :page, :steps, :expected, true, :src)
                on conflict (test_case_id) do update set
                    test_case_name = excluded.test_case_name,
                    page = excluded.page,
                    steps = excluded.steps,
                    expected_result = excluded.expected_result,
                    enabled = true,
                    source_file = excluded.source_file,
                    updated_at = now()
            """), {
                "id": new_id,
                "name": name,
                "page": template["page"],
                "steps": fill(template["steps"], data),
                "expected": template["expected_result"],
                "src": f"batch {batch_id}",
            })
            generated.append(new_id)
    return generated