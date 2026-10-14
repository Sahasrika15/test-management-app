import sys

from core.csv_import import validate_csv_text

path = sys.argv[1]
with open(path, encoding="utf-8-sig") as f:
    result = validate_csv_text(f.read())

if result.errors:
    print(f"Errors ({len(result.errors)}):")
    for error in result.errors:
        print("  " + error)
print(f"Valid rows: {len(result.rows)}")
for row in result.rows:
    print(f"  {row['test_case_id']}  enabled={row['enabled']}  {row['test_case_name']}")