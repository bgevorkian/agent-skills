from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

try:
    from trino.auth import BasicAuthentication, CertificateAuthentication, JWTAuthentication
    from trino.dbapi import connect
except ImportError:  # pragma: no cover - exercised only without dependency
    BasicAuthentication = CertificateAuthentication = JWTAuthentication = None
    connect = None

ALLOWED_FIRST = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "VALUES", "TABLE"}
FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE",
    "CALL", "GRANT", "REVOKE", "COMMENT", "ANALYZE", "REFRESH", "SET", "RESET",
    "USE", "PREPARE", "EXECUTE", "DEALLOCATE", "START", "COMMIT", "ROLLBACK",
}
TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false")


def default_port(http_scheme: str) -> int:
    return 443 if http_scheme == "https" else 8080


def mask_literals_and_comments(sql: str) -> str:
    output = list(sql)
    index = 0
    state = "code"
    while index < len(sql):
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "code":
            if char == "'":
                output[index] = " "
                state = "single"
            elif char == '"':
                output[index] = " "
                state = "double"
            elif char == "`":
                output[index] = " "
                state = "backtick"
            elif char == "-" and nxt == "-":
                output[index] = output[index + 1] = " "
                index += 1
                state = "line_comment"
            elif char == "/" and nxt == "*":
                output[index] = output[index + 1] = " "
                index += 1
                state = "block_comment"
        elif state == "single":
            output[index] = " "
            if char == "'" and nxt == "'":
                output[index + 1] = " "
                index += 1
            elif char == "'":
                state = "code"
        elif state == "double":
            output[index] = " "
            if char == '"' and nxt == '"':
                output[index + 1] = " "
                index += 1
            elif char == '"':
                state = "code"
        elif state == "backtick":
            output[index] = " "
            if char == "`" and nxt == "`":
                output[index + 1] = " "
                index += 1
            elif char == "`":
                state = "code"
        elif state == "line_comment":
            output[index] = " "
            if char in "\r\n":
                state = "code"
        elif state == "block_comment":
            output[index] = " "
            if char == "*" and nxt == "/":
                output[index + 1] = " "
                index += 1
                state = "code"
        index += 1
    if state in {"single", "double", "backtick", "block_comment"}:
        raise ValueError("unterminated SQL literal or comment")
    return "".join(output)


def validate_readonly_sql(sql: str) -> str:
    if not sql.strip():
        raise ValueError("SQL is empty")
    masked = mask_literals_and_comments(sql).strip()
    if masked.endswith(";"):
        masked = masked[:-1].rstrip()
    if not masked:
        raise ValueError("SQL is empty")
    if ";" in masked:
        raise ValueError("multiple SQL statements are not allowed")
    match = re.match(r"([A-Za-z]+)", masked)
    first = match.group(1).upper() if match else ""
    if first not in ALLOWED_FIRST:
        raise ValueError(f"statement {first or '<unknown>'} is not allowed in read-only mode")
    tokens = {token.upper() for token in re.findall(r"\b[A-Za-z]+\b", masked)}
    blocked = sorted(tokens & FORBIDDEN)
    if blocked:
        raise ValueError(f"write/administrative keyword is not allowed: {blocked[0]}")
    return sql


def read_value(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


def rows_payload(columns: list[str], rows: list[list[Any]], truncated: bool = False) -> dict[str, Any]:
    payload_rows = [{column: jsonable(value) for column, value in zip(columns, row)} for row in rows]
    payload: dict[str, Any] = {"rows": payload_rows, "row_count": len(payload_rows)}
    if truncated:
        payload["truncated"] = True
    return payload


def quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def sql_string(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def resolve_verify(args: argparse.Namespace) -> bool | str:
    return args.ca_bundle or args.verify


def build_auth(user: str) -> Any:
    if connect is None:
        raise RuntimeError("trino is not installed; run with: uv run --python 3.13 --with trino python ...")
    password = os.environ.get("TRINO_PASSWORD")
    token = os.environ.get("TRINO_ACCESS_TOKEN")
    cert = os.environ.get("TRINO_CERT")
    key = os.environ.get("TRINO_KEY")
    modes = sum(bool(value) for value in [password, token, cert or key])
    if modes > 1:
        raise ValueError("configure only one Trino auth mode at a time")
    if token:
        return JWTAuthentication(token)
    if password:
        return BasicAuthentication(user, password)
    if cert or key:
        if not (cert and key):
            raise ValueError("TRINO_CERT and TRINO_KEY must be set together")
        return CertificateAuthentication(cert, key)
    return None


def build_connect_kwargs(args: argparse.Namespace, *, catalog: str | None = None, schema: str | None = None) -> dict[str, Any]:
    if connect is None:
        raise RuntimeError("trino is not installed; run with: uv run --python 3.13 --with trino python ...")
    if not args.host:
        raise ValueError("missing Trino host: set TRINO_HOST or pass --host")
    if not args.user:
        raise ValueError("missing Trino user: set TRINO_USER or pass --user")
    kwargs: dict[str, Any] = {
        "host": args.host,
        "port": args.port,
        "user": args.user,
        "catalog": catalog,
        "schema": schema,
        "http_scheme": args.http_scheme,
        "auth": build_auth(args.user),
        "request_timeout": args.timeout,
        "verify": resolve_verify(args),
        "session_properties": {"query_max_execution_time": f"{int(args.timeout)}s"},
    }
    return kwargs


def open_connection(args: argparse.Namespace, *, catalog: str | None = None, schema: str | None = None) -> Any:
    return connect(**build_connect_kwargs(args, catalog=catalog, schema=schema))


def fetch_payload(cursor: Any, max_rows: int) -> dict[str, Any]:
    rows = cursor.fetchmany(max_rows + 1)
    truncated = len(rows) > max_rows
    rows = rows[:max_rows]
    columns = [column[0] for column in cursor.description] if cursor.description else []
    return rows_payload(columns, rows, truncated)


def catalog_required(args: argparse.Namespace, value: str | None) -> str:
    catalog = value or args.catalog
    if not catalog:
        raise ValueError("missing catalog: set TRINO_CATALOG, pass --catalog, or use fully qualified SQL")
    return catalog


def schema_required(args: argparse.Namespace, value: str | None) -> str:
    schema = value or args.schema
    if not schema:
        raise ValueError("missing schema: set TRINO_SCHEMA or pass --schema")
    return schema


def run_query(args: argparse.Namespace, sql: str, *, catalog: str | None = None, schema: str | None = None) -> dict[str, Any]:
    connection = open_connection(args, catalog=catalog, schema=schema)
    try:
        cursor = connection.cursor()
        cursor.execute(sql)
        return fetch_payload(cursor, args.max_rows)
    finally:
        connection.close()


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="tr.py", description="generic read-only Trino JSON CLI")
    default_scheme = os.environ.get("TRINO_HTTP_SCHEME", "https")
    command.add_argument("--host", default=os.environ.get("TRINO_HOST"))
    port = os.environ.get("TRINO_PORT")
    command.add_argument("--port", type=int, default=int(port) if port else default_port(default_scheme))
    command.add_argument("--user", default=os.environ.get("TRINO_USER"))
    command.add_argument("--catalog", default=os.environ.get("TRINO_CATALOG"))
    command.add_argument("--schema", default=os.environ.get("TRINO_SCHEMA"))
    command.add_argument("--http-scheme", choices=["http", "https"], default=default_scheme)
    command.add_argument("--verify", action=argparse.BooleanOptionalAction, default=env_bool("TRINO_VERIFY", True))
    command.add_argument("--ca-bundle", default=os.environ.get("TRINO_CA_BUNDLE"))
    command.add_argument("--timeout", type=float, default=30.0)
    command.add_argument("--max-rows", type=int, default=10_000)
    subcommands = command.add_subparsers(dest="command", required=True)

    query = subcommands.add_parser("query", help="run guarded read-only SQL")
    query.add_argument("--sql", required=True, help="literal SQL, @file.sql, or - for stdin")

    subcommands.add_parser("list-catalogs", help="list catalogs")

    schemas = subcommands.add_parser("list-schemas", help="list schemas in a catalog")
    schemas.add_argument("--catalog")

    tables = subcommands.add_parser("list-tables", help="list tables in a catalog schema")
    tables.add_argument("--catalog")
    tables.add_argument("--schema")

    describe = subcommands.add_parser("describe-table", help="describe one table")
    describe.add_argument("--catalog")
    describe.add_argument("--schema")
    describe.add_argument("--table", required=True)
    return command


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "query":
        return run_query(args, validate_readonly_sql(read_value(args.sql)), catalog=args.catalog, schema=args.schema)
    if args.command == "list-catalogs":
        return run_query(args, "SHOW CATALOGS")
    if args.command == "list-schemas":
        catalog = catalog_required(args, args.catalog)
        sql = f"SELECT schema_name FROM {quote_identifier(catalog)}.information_schema.schemata ORDER BY schema_name"
        return run_query(args, sql, catalog=catalog)
    if args.command == "list-tables":
        catalog = catalog_required(args, args.catalog)
        schema = schema_required(args, args.schema)
        sql = (
            f"SELECT table_schema, table_name, table_type FROM {quote_identifier(catalog)}.information_schema.tables "
            f"WHERE table_schema = {sql_string(schema)} ORDER BY table_name"
        )
        return run_query(args, sql, catalog=catalog, schema=schema)
    catalog = catalog_required(args, args.catalog)
    schema = schema_required(args, args.schema)
    sql = (
        f"SELECT column_name, data_type, is_nullable, column_default FROM {quote_identifier(catalog)}.information_schema.columns "
        f"WHERE table_schema = {sql_string(schema)} AND table_name = {sql_string(args.table)} "
        "ORDER BY ordinal_position"
    )
    return run_query(args, sql, catalog=catalog, schema=schema)


def main() -> None:
    try:
        payload = dispatch(parser().parse_args())
        sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except Exception as error:
        print(f"Trino command failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
