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


def claim_next_run():
    """Mark the oldest queued run as running and return it, or None if there are none."""
    sql = text("""
        update executions
        set status = 'running', started_at = now()
        where id = (
            select id from executions
            where status = 'queued'
            order by id
            limit 1
            for update skip locked
        )
        returning id, app_url
    """)
    with get_engine().begin() as conn:
        row = conn.execute(sql).mappings().first()
    return dict(row) if row else None


def get_queued_results(run_id):
    """Return the queued test results for one run, with their test case details."""
    sql = text("""
        select r.id, t.test_case_id, t.test_case_name, t.page, t.steps
        from test_results r
        join test_cases t on t.id = r.test_case_id
        where r.execution_id = :run_id and r.status = 'queued'
        order by t.test_case_id
    """)
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(sql, {"run_id": run_id}).mappings()]


def save_result(result_id, status, failed_step, error_message, video_path, duration_ms):
    sql = text("""
        update test_results
        set status = :status,
            failed_step = :failed_step,
            error_message = :error_message,
            video_path = :video_path,
            duration_ms = :duration_ms,
            completed_at = now()
        where id = :result_id
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {
            "result_id": result_id,
            "status": status,
            "failed_step": failed_step,
            "error_message": error_message,
            "video_path": video_path,
            "duration_ms": duration_ms,
        })


def finish_run(run_id):
    sql = text("""
        update executions
        set status = 'completed', completed_at = now()
        where id = :run_id
    """)
    with get_engine().begin() as conn:
        conn.execute(sql, {"run_id": run_id})

def get_run_results(run_id):
    """Return every test result for one run, with the expected result and video path."""
    sql = text("""
        select t.test_case_id, t.test_case_name, t.expected_result,
               r.status, r.failed_step, r.error_message, r.duration_ms, r.video_path
        from test_results r
        join test_cases t on t.id = r.test_case_id
        where r.execution_id = :run_id
        order by t.test_case_id
    """)
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(sql, {"run_id": run_id}).mappings()]

def get_dashboard_stats():
    """Summary numbers, recent run trend, and latest failures for the Dashboard."""
    totals_sql = text("""
        select
            (select count(*) from test_cases) as total_cases,
            (select count(*) from test_cases where enabled) as enabled_cases,
            (select count(*) from executions) as total_runs,
            (select count(*) from test_results where status = 'passed') as passed,
            (select count(*) from test_results where status = 'failed') as failed,
            (select coalesce(avg(duration_ms), 0) from test_results
              where status in ('passed', 'failed')) as avg_ms
    """)
    trend_sql = text("""
        select e.id as run_id, e.app_url, e.created_at,
               count(r.id) filter (where r.status = 'passed') as passed,
               count(r.id) filter (where r.status = 'failed') as failed
        from executions e
        left join test_results r on r.execution_id = e.id
        group by e.id, e.app_url, e.created_at
        order by e.id desc
        limit 10
    """)
    failures_sql = text("""
        select e.id as run_id, t.test_case_id, t.test_case_name,
               r.failed_step, r.error_message, e.created_at
        from test_results r
        join test_cases t on t.id = r.test_case_id
        join executions e on e.id = r.execution_id
        where r.status = 'failed'
        order by r.id desc
        limit 10
    """)
    with get_engine().connect() as conn:
        totals = dict(conn.execute(totals_sql).mappings().one())
        trend = [dict(r) for r in conn.execute(trend_sql).mappings()]
        failures = [dict(r) for r in conn.execute(failures_sql).mappings()]
    return {
        "totals": totals,
        "trend": list(reversed(trend)),  # oldest first, for the chart
        "failures": failures,
    }