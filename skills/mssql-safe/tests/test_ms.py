from __future__ import annotations

from argparse import Namespace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
import os
import sys
from uuid import UUID

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from ms import (  # noqa: E402
    build_connect_kwargs,
    env_bool,
    ensure_write_allowed,
    jsonable,
    read_params,
    validate_readonly_sql,
    validate_single_statement,
)


def expect_rejected(func, value) -> None:
    try:
        func(value)
    except ValueError:
        return
    raise AssertionError(f"expected rejection: {value}")


def main() -> None:
    accepted = [
        "SELECT 1",
        "-- note\nSELECT 'drop table x' AS text;",
        "WITH data AS (SELECT 1) SELECT * FROM data",
        "VALUES (1), (2)",
        "SELECT [drop] FROM [safe]]name]",
        "/* outer /* nested */ comment */ SELECT 1",
    ]
    for sql in accepted:
        assert validate_readonly_sql(sql) == sql

    rejected = [
        "INSERT INTO x VALUES (1)",
        "WITH changed AS (DELETE FROM x OUTPUT deleted.*) SELECT * FROM changed",
        "SELECT 1; SELECT 2",
        "EXEC dbo.DoThing",
        "SET NOCOUNT ON",
        "SELECT 'unterminated",
        "",
    ]
    for sql in rejected:
        expect_rejected(validate_readonly_sql, sql)

    expect_rejected(validate_single_statement, "UPDATE x SET y = 1; DELETE FROM x")

    os.environ.pop("FLAG_TEST", None)
    assert env_bool("FLAG_TEST", True) is True
    os.environ["FLAG_TEST"] = "off"
    assert env_bool("FLAG_TEST", True) is False
    os.environ["FLAG_TEST"] = "maybe"
    expect_rejected(lambda _: env_bool("FLAG_TEST", True), None)
    os.environ.pop("FLAG_TEST", None)

    os.environ.pop("MSSQL_ALLOW_WRITE", None)
    try:
        ensure_write_allowed(True)
    except ValueError as error:
        assert "MSSQL_ALLOW_WRITE=true" in str(error)
    else:
        raise AssertionError("write gate should reject missing env")
    os.environ["MSSQL_ALLOW_WRITE"] = "true"
    try:
        ensure_write_allowed(False)
    except ValueError as error:
        assert "--confirm-write" in str(error)
    else:
        raise AssertionError("write gate should require confirmation")
    ensure_write_allowed(True)
    os.environ.pop("MSSQL_ALLOW_WRITE", None)

    assert read_params('[1, 2]') == [1, 2]
    assert read_params('{"x": 1}') == {"x": 1}
    expect_rejected(read_params, '"nope"')

    assert jsonable(Decimal("9.90")) == "9.90"
    assert jsonable(datetime(2026, 1, 2, tzinfo=timezone.utc)) == "2026-01-02T00:00:00+00:00"
    assert jsonable(UUID("12345678-1234-5678-1234-567812345678")) == "12345678-1234-5678-1234-567812345678"
    assert jsonable(b"\x00\xff") == "00ff"
    assert jsonable([Decimal("1.2")]) == ["1.2"]

    os.environ["MSSQL_PASSWORD"] = "secret"
    args = Namespace(
        host="db.example.net",
        port=1433,
        database="app",
        user="reader",
        connect_timeout=5,
        timeout=30,
        charset="UTF-8",
        appname="mssql-safe",
        encryption="require",
        tds_version="7.4",
    )
    kwargs = build_connect_kwargs(args, read_only=True)
    assert kwargs["server"] == "db.example.net"
    assert kwargs["database"] == "app"
    assert kwargs["user"] == "reader"
    assert kwargs["password"] == "secret"
    assert kwargs["read_only"] is True
    assert kwargs["encryption"] == "require"
    os.environ.pop("MSSQL_PASSWORD", None)

    print("mssql-safe tests: OK")


if __name__ == "__main__":
    main()
