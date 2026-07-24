from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import sys

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from pg import jsonable, read_hosts, validate_readonly_sql  # noqa: E402


def expect_rejected(sql: str) -> None:
    try:
        validate_readonly_sql(sql)
    except ValueError:
        return
    raise AssertionError(f"SQL should have been rejected: {sql}")


def main() -> None:
    accepted = [
        "SELECT 1",
        "-- report\nSELECT 'delete from users' AS note;",
        "WITH data AS (SELECT 1) SELECT * FROM data",
        "SELECT $$drop table hidden$$ AS text",
        "SELECT $tag$update x$tag$ AS text",
        "/* outer /* nested */ comment */ SHOW statement_timeout",
        "VALUES (1), (2)",
        "TABLE public.safe_view",
    ]
    for sql in accepted:
        assert validate_readonly_sql(sql) == sql

    rejected = [
        "INSERT INTO x VALUES (1)",
        "WITH changed AS (DELETE FROM x RETURNING *) SELECT * FROM changed",
        "SELECT 1; SELECT 2",
        "EXPLAIN ANALYZE DELETE FROM x",
        "COPY users TO PROGRAM 'cat'",
        "SET ROLE admin",
        "SELECT 'unterminated",
        "SELECT $$unterminated",
        "",
    ]
    for sql in rejected:
        expect_rejected(sql)

    assert read_hosts("db-a,db-b,db-a") == ["db-a", "db-b"]
    assert jsonable(Decimal("9.90")) == "9.90"
    assert jsonable(datetime(2026, 1, 2, tzinfo=timezone.utc)) == "2026-01-02T00:00:00+00:00"
    assert jsonable(b"\x00\xff") == "00ff"
    print("postgres-readonly tests: OK")


if __name__ == "__main__":
    main()
