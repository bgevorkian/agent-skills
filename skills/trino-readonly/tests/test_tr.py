from __future__ import annotations

from argparse import Namespace
from datetime import date
from decimal import Decimal
from pathlib import Path
import os
import sys
from uuid import UUID

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from tr import (  # noqa: E402
    build_auth,
    build_connect_kwargs,
    default_port,
    env_bool,
    jsonable,
    quote_identifier,
    resolve_verify,
    rows_payload,
    sql_string,
    validate_readonly_sql,
)
from trino.auth import BasicAuthentication, JWTAuthentication  # noqa: E402


def expect_rejected(sql: str) -> None:
    try:
        validate_readonly_sql(sql)
    except ValueError:
        return
    raise AssertionError(f"SQL should have been rejected: {sql}")


def main() -> None:
    accepted = [
        "SELECT 1",
        " -- note\n SELECT 'drop table x' AS text;",
        "/* report */ WITH x AS (SELECT 1) SELECT * FROM x",
        "SHOW SCHEMAS",
        "DESCRIBE orders",
        "TABLE catalog.schema.table_name",
        "VALUES 1, 2",
    ]
    for sql in accepted:
        assert validate_readonly_sql(sql) == sql

    rejected = [
        "INSERT INTO x VALUES (1)",
        "WITH old AS (DELETE FROM x RETURNING *) SELECT * FROM old",
        "SELECT 1; DROP TABLE x",
        "USE analytics",
        "SELECT 'unterminated",
        "",
    ]
    for sql in rejected:
        expect_rejected(sql)

    os.environ.pop("TRINO_VERIFY", None)
    assert env_bool("TRINO_VERIFY", True) is True
    os.environ["TRINO_VERIFY"] = "no"
    assert env_bool("TRINO_VERIFY", True) is False
    os.environ["TRINO_VERIFY"] = "bad"
    try:
        env_bool("TRINO_VERIFY", True)
    except ValueError:
        pass
    else:
        raise AssertionError("invalid bool should fail")
    os.environ.pop("TRINO_VERIFY", None)

    assert default_port("https") == 443
    assert default_port("http") == 8080
    assert quote_identifier('ice"berg') == '"ice""berg"'
    assert sql_string("o'reilly") == "'o''reilly'"
    assert jsonable(Decimal("1.20")) == "1.20"
    assert jsonable(date(2026, 1, 2)) == "2026-01-02"
    assert jsonable(UUID("12345678-1234-5678-1234-567812345678")) == "12345678-1234-5678-1234-567812345678"
    assert rows_payload(["n", "payload"], [[1, b"\x01\x02"]]) == {"rows": [{"n": 1, "payload": "0102"}], "row_count": 1}

    for name in ["TRINO_PASSWORD", "TRINO_ACCESS_TOKEN", "TRINO_CERT", "TRINO_KEY"]:
        os.environ.pop(name, None)
    os.environ["TRINO_ACCESS_TOKEN"] = "token"
    assert isinstance(build_auth("analyst"), JWTAuthentication)
    os.environ.pop("TRINO_ACCESS_TOKEN", None)
    os.environ["TRINO_PASSWORD"] = "secret"
    os.environ["TRINO_USER"] = "analyst"
    assert isinstance(build_auth("analyst"), BasicAuthentication)
    os.environ.pop("TRINO_PASSWORD", None)

    args = Namespace(
        host="trino.example.net",
        port=443,
        user="analyst",
        catalog="iceberg",
        schema="analytics",
        http_scheme="https",
        verify=True,
        ca_bundle=None,
        timeout=45.0,
        max_rows=100,
    )
    kwargs = build_connect_kwargs(args, catalog=args.catalog, schema=args.schema)
    assert kwargs["host"] == "trino.example.net"
    assert kwargs["catalog"] == "iceberg"
    assert kwargs["schema"] == "analytics"
    assert kwargs["request_timeout"] == 45.0
    assert kwargs["verify"] is True
    assert kwargs["session_properties"]["query_max_execution_time"] == "45s"
    assert resolve_verify(args) is True

    print("trino-readonly tests: OK")


if __name__ == "__main__":
    main()
