import functools
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


def save_result(result_id, status, failed_step, error_message, video_data, duration_ms):
    sql = text("""
        update test_results
        set status = :status,
            failed_step = :failed_step,
            error_message = :error_message,
            video_data = :video_data,
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
            "video_data": video_data,
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
    """Return every test result for one run. Video bytes are not loaded here; has_video says whether one exists."""
    sql = text("""
        select r.id, t.test_case_id, t.test_case_name, t.expected_result,
               r.status, r.failed_step, r.error_message, r.duration_ms, r.video_path,
               (r.video_data is not null) as has_video
        from test_results r
        join test_cases t on t.id = r.test_case_id
        where r.execution_id = :run_id
        order by t.test_case_id
    """)
    with get_engine().connect() as conn:
        return [dict(row) for row in conn.execute(sql, {"run_id": run_id}).mappings()]

@functools.lru_cache(maxsize=64)
def get_result_video(result_id):
    with get_engine().connect() as conn:
        row = conn.execute(
            text("select video_data from test_results where id = :id"), {"id": result_id}
        ).first()
    return bytes(row[0]) if row and row[0] is not None else None

def get_dashboard_stats():
    """Summary numbers, recent run trend, and latest failures for the Dashboard in a single roundtrip."""
    sql = text("""
        with totals as (
            select
                (select count(*) from test_cases) as total_cases,
                (select count(*) from test_cases where enabled) as enabled_cases,
                (select count(*) from executions) as total_runs,
                (select count(*) filter (where status = 'passed') from test_results) as passed,
                (select count(*) filter (where status = 'failed') from test_results) as failed,
                (select coalesce(avg(duration_ms) filter (where status in ('passed', 'failed')), 0) from test_results) as avg_ms
        ),
        trend as (
            select coalesce(json_agg(t), '[]'::json) as trend_data from (
                select e.id as run_id, e.app_url,
                       to_char(e.created_at, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at_iso,
                       count(r.id) filter (where r.status = 'passed') as passed,
                       count(r.id) filter (where r.status = 'failed') as failed
                from executions e
                left join test_results r on r.execution_id = e.id
                group by e.id, e.app_url, e.created_at
                order by e.id desc
                limit 10
            ) t
        ),
        failures as (
            select coalesce(json_agg(f), '[]'::json) as failures_data from (
                select e.id as run_id, t.test_case_id, t.test_case_name,
                       r.failed_step, r.error_message,
                       to_char(e.created_at, 'YYYY-MM-DD"T"HH24:MI:SS"Z"') as created_at_iso
                from test_results r
                join test_cases t on t.id = r.test_case_id
                join executions e on e.id = r.execution_id
                where r.status = 'failed'
                order by r.id desc
                limit 10
            ) f
        ),
        last_run as (
            select created_at from executions
            where exists (select 1 from test_results r where r.execution_id = executions.id)
            order by id desc limit 1
        )
        select
            row_to_json(totals.*) as totals,
            trend.trend_data as trend,
            failures.failures_data as failures,
            last_run.created_at as last_run_at
        from totals, trend, failures
        left join last_run on true;
    """)
    with get_engine().connect() as conn:
        row = conn.execute(sql).mappings().one()
        totals = dict(row["totals"]) if row["totals"] else {}
        trend = list(row["trend"]) if row["trend"] else []
        failures = list(row["failures"]) if row["failures"] else []
        last_run_at = row["last_run_at"]

    for r in trend:
        if "created_at_iso" in r and "created_at" not in r:
            try:
                r["created_at"] = datetime.datetime.fromisoformat(r["created_at_iso"].replace("Z", "+00:00"))
            except Exception:
                r["created_at"] = last_run_at

    for f in failures:
        if "created_at_iso" in f and "created_at" not in f:
            try:
                f["created_at"] = datetime.datetime.fromisoformat(f["created_at_iso"].replace("Z", "+00:00"))
            except Exception:
                f["created_at"] = last_run_at

    last_label = f"Last run: {last_run_at:%d %b, %H:%M}" if last_run_at else "No runs yet"

    return {
        "totals": totals,
        "trend": list(reversed(trend)),  # oldest first, for the chart
        "failures": failures,
        "last_run_at": last_run_at.isoformat() if last_run_at else None,
        "last_label": last_label,
    }

def recover_stale_runs(older_than_minutes=60):
    """Close runs left running by a worker that died. Their unfinished tests are marked failed."""
    window = f"{int(older_than_minutes)} minutes"
    with get_engine().begin() as conn:
        conn.execute(text("""
            update test_results r
            set status = 'failed',
                failed_step = 0,
                error_message = 'Runner stopped before this test ran; run again',
                completed_at = now()
            from executions e
            where r.execution_id = e.id
              and r.status = 'queued'
              and e.status = 'running'
              and e.started_at < now() - cast(:window as interval)
        """), {"window": window})
        conn.execute(text("""
            update executions
            set status = 'completed', completed_at = now()
            where status = 'running'
              and started_at < now() - cast(:window as interval)
        """), {"window": window})


def claim_run(run_id):
    """Mark one specific queued run as running. Returns None if it is not queued."""
    sql = text("""
        update executions
        set status = 'running', started_at = now()
        where id = :run_id and status = 'queued'
        returning id, app_url
    """)
    with get_engine().begin() as conn:
        row = conn.execute(sql, {"run_id": run_id}).mappings().first()
    return dict(row) if row else None