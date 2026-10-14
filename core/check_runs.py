from core.runs import create_run, list_runs
from core.test_cases import list_test_cases

if __name__ == "__main__":
    ids = [case["test_case_id"] for case in list_test_cases()]

    run_id, queued = create_run("https://example.com", ids, app_name="Demo")
    print(f"Created run {run_id} with {queued} queued result(s)")

    try:
        create_run("example.com", ids)
    except ValueError as error:
        print("Rejected bad URL:", error)

    print("Runs:")
    for run in list_runs():
        print(
            f"  run {run['id']}  {run['status']}  total={run['total']} "
            f"passed={run['passed']} failed={run['failed']}  {run['app_url']}"
        )