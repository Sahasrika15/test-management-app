from sqlalchemy import text

from db.connection import get_engine


def create_run(app_url, test_case_ids, app_name=None):
    """Create one run and a queued result for each enabled, selected test case."""
    app_url = (app_url or "").strip()
    if not app_url.startswith(("http://", "https://")):
        raise ValueError("Application URL must start with http:// or https://")
    if not test_case_ids:
        raise ValueError("Choose at least one test case")

    with get_engine().begin() as conn:
        run_id = conn.execute(
            text("""
                insert into executions (status, app_url, app_name)
                values ('queued', :app_url, :app_name)
                returning id
            """),
            {"app_url": app_url, "app_name": app_name},
        ).scalar_one()

        queued = conn.execute(
            text("""
                insert into test_results (execution_id, test_case_id, status)
                select :run_id, id, 'queued'
                from test_cases
                where test_case_id = any(:ids) and enabled = true
                order by test_case_id
            """),
            {"run_id": run_id, "ids": list(test_case_ids)},
        ).rowcount

        if queued == 0:
            raise ValueError("None of the selected test cases are enabled")

    return run_id, queued


def list_runs():
    """Return every run, newest first, with counts for each status."""
    sql = text("""
        select e.id, e.app_url, e.app_name, e.status, e.created_at,
               count(r.id) as total,
               count(r.id) filter (where r.status = 'passed') as passed,
               count(r.id) filter (where r.status = 'failed') as failed
        from executions e
        left join test_results r on r.execution_id = e.id
        group by e.id
        order by e.id desc
    """)
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(sql).mappings()]