from sqlalchemy import text

from db.connection import get_engine


def save_test_cases(cases, source_file=None):
    """Add or update test cases for this file. Cases that are no longer in the file are removed
    only when no run has used them. Cases with run history are turned off instead, so past
    results are never lost."""
    rows = [{**c, "source_file": source_file} for c in cases]
    ids = [c["test_case_id"] for c in cases]

    upsert_sql = text("""
        insert into test_cases
            (test_case_id, test_case_name, page, steps, expected_result, enabled, source_file)
        values
            (:test_case_id, :test_case_name, :page, :steps, :expected_result, :enabled, :source_file)
        on conflict (test_case_id) do update set
            test_case_name = excluded.test_case_name,
            page = excluded.page,
            steps = excluded.steps,
            expected_result = excluded.expected_result,
            enabled = excluded.enabled,
            source_file = excluded.source_file,
            updated_at = now()
    """)

    # Cases from this file that are no longer in the upload and have never been run.
    remove_sql = text("""
        delete from test_cases t
        where t.source_file is not distinct from :src
          and not (t.test_case_id = any(:ids))
          and not exists (select 1 from test_results r where r.test_case_id = t.id)
    """)

    # Cases from this file that are no longer in the upload but have run history.
    disable_sql = text("""
        update test_cases
        set enabled = false, updated_at = now()
        where source_file is not distinct from :src
          and not (test_case_id = any(:ids))
    """)

    with get_engine().begin() as conn:
        conn.execute(upsert_sql, rows)
        conn.execute(remove_sql, {"src": source_file, "ids": ids})
        conn.execute(disable_sql, {"src": source_file, "ids": ids})

    return len(rows)


def list_test_cases(source_file=None):
    """Return test cases ordered by ID. Pass a file name to show only that upload.
    Pass an empty string to show cases imported before file names were tracked."""
    base = """
        select test_case_id, test_case_name, page, steps, expected_result, enabled, source_file
        from test_cases
    """
    params = {}
    if source_file is None:
        sql = base + " order by test_case_id"
    elif source_file == "":
        sql = base + " where source_file is null order by test_case_id"
    else:
        sql = base + " where source_file = :src order by test_case_id"
        params["src"] = source_file
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(text(sql), params).mappings()]


def list_sources():
    """Return each uploaded file with its case count, most recently updated first."""
    sql = text("""
        select source_file, max(updated_at) as last_seen, count(*) as total
        from test_cases
        group by source_file
        order by max(updated_at) desc
    """)
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(sql).mappings()]


def set_enabled(test_case_id, enabled):
    """Turn one test case on or off. Returns False if the ID doesn't exist."""
    sql = text("""
        update test_cases
        set enabled = :enabled, updated_at = now()
        where test_case_id = :test_case_id
    """)
    with get_engine().begin() as conn:
        result = conn.execute(sql, {"test_case_id": test_case_id, "enabled": enabled})
    return result.rowcount > 0