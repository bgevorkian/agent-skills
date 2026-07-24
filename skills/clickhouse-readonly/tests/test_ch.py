from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
import sys

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from ch import jsonable, result_payload, validate_readonly_sql  # noqa: E402


def expect_rejected(sql: str) -> None:
    try:
        validate_readonly_sql(sql)
    except ValueError:
        return
    raise AssertionError(f"SQL should have been rejected: {sql}")


def main() -> None:
    accepted = [
        "SELECT 1",
        " -- comment\n SELECT 'drop table x' AS text;",
        "/* report */ WITH x AS (SELECT 1) SELECT * FROM x",
        "SHOW TABLES",
        "DESCRIBE TABLE system.numbers",
        "EXPLAIN SELECT 1",
    ]
    for sql in accepted:
        assert validate_readonly_sql(sql) == sql

    rejected = [
        "INSERT INTO x VALUES (1)",
        "WITH old AS (DELETE FROM x RETURNING *) SELECT * FROM old",
        "SELECT 1; DROP TABLE x",
        "SYSTEM FLUSH LOGS",
        "SELECT 'unterminated",
        "",
    ]
    for sql in rejected:
        expect_rejected(sql)

    assert jsonable(Decimal("1.20")) == "1.20"
    assert jsonable(date(2026, 1, 2)) == "2026-01-02"

    class Result:
        column_names = ["n", "payload"]
        result_rows = [(1, b"\x01\x02")]

    assert result_payload(Result()) == {"rows": [{"n": 1, "payload": "0102"}], "row_count": 1}
    print("clickhouse-readonly tests: OK")


if __name__ == "__main__":
    main()
