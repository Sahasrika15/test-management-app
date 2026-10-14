import sys

from core.importer import import_csv_text
from core.test_cases import list_test_cases

if __name__ == "__main__":
    with open(sys.argv[1], encoding="utf-8-sig") as f:
        result, saved = import_csv_text(f.read())

    if result.ok:
        print(f"Saved {saved} test case(s).")
    else:
        print(f"Nothing saved. {len(result.errors)} error(s):")
        for error in result.errors:
            print("  " + error)

    print("Test cases in database:")
    for case in list_test_cases():
        print(f"  {case['test_case_id']}  enabled={case['enabled']}  {case['test_case_name']}")