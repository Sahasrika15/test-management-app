from sqlalchemy import text

from db.connection import get_engine


def save_test_cases(cases: list[dict]) -> int:
    """Insert new test cases, or update existing ones with the same ID."""
    sql = text("""
        insert into test_cases
            (test_case_id, test_case_name, page, steps, expected_result, enabled)
        values
            (:test_case_id, :test_case_name, :page, :steps, :expected_result, :enabled)
        on conflict (test_case_id) do update set
            test_case_name = excluded.test_case_name,
            page = excluded.page,
            steps = excluded.steps,
            expected_result = excluded.expected_result,
            enabled = excluded.enabled,
            updated_at = now()
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, cases)
    return len(cases)


def list_test_cases() -> list[dict]:
    """Return all test cases ordered by ID."""
    sql = text("""
        select test_case_id, test_case_name, page, steps, expected_result, enabled
        from test_cases
        order by test_case_id
    """)
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(sql).mappings()]


def set_enabled(test_case_id: str, enabled: bool) -> bool:
    """Turn one test case on or off. Returns False if the ID doesn't exist."""
    sql = text("""
        update test_cases
        set enabled = :enabled, updated_at = now()
        where test_case_id = :test_case_id
    """)
    with get_engine().begin() as conn:
        result = conn.execute(sql, {"test_case_id": test_case_id, "enabled": enabled})
    return result.rowcount > 0