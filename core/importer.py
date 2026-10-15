from core.csv_import import validate_csv_text
from core.test_cases import save_test_cases


def import_csv_text(content, source_file=None):
    """Validate a CSV and save its rows with the file name. Nothing is saved if any row is invalid."""
    result = validate_csv_text(content)
    if not result.ok or not result.rows:
        return result, 0
    saved = save_test_cases(result.rows, source_file)
    return result, saved