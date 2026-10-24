import sys
from pathlib import Path


API_DIR = Path(__file__).resolve().parents[1] / "backend" / "api"
sys.path.insert(0, str(API_DIR))

from verify import run_tests


FIXES = {
    "sum_off_by_one": "def sum_numbers(start, end):\n    return sum(range(start, end + 1))\n",
    "none_check": "def item_count(items):\n    if items is None:\n        return 0\n    return len(items)\n",
}


def main():
    for fixture_id, fixed_code in FIXES.items():
        before = run_tests(fixture_id)
        after = run_tests(fixture_id, fixed_code)
        print(f"{fixture_id}: {'FAIL' if before['status'] == 'failed' else before['status'].upper()} before")
        print(f"{fixture_id}: {'PASS' if after['status'] == 'passed' else after['status'].upper()} after")
        if before["status"] != "failed" or after["status"] != "passed":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
