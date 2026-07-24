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
    import pymssql
except ImportError:  # pragma: no cover - exercised only without dependency
    pymssql = None

ALLOWED_READ_FIRST = {"SELECT", "WITH", "VALUES"}
FORBIDDEN_READ_TOKENS = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE",
    "EXEC", "EXECUTE", "CALL", "GRANT", "REVOKE", "DENY", "BACKUP", "RESTORE",
    "DBCC", "BULK", "KILL", "WAITFOR", "SHUTDOWN", "USE", "SET",
}
ENCRYPTION_CHOICES = ("default", "off", "request", "require")
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


def mask_literals_and_comments(sql: str) -> str:
    output = list(sql)
    index = 0
    state = "code"
    block_depth = 0
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
            elif char == "[":
                output[index] = " "
                state = "bracket"
            elif char == "-" and nxt == "-":
                output[index] = output[index + 1] = " "
                index += 1
                state = "line_comment"
            elif char == "/" and nxt == "*":
                output[index] = output[index + 1] = " "
                index += 1
                state = "block_comment"
                block_depth = 1
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
        elif state == "bracket":
            output[index] = " "
            if char == "]" and nxt == "]":
                output[index + 1] = " "
                index += 1
            elif char == "]":
                state = "code"
        elif state == "line_comment":
            output[index] = " "
            if char in "\r\n":
                state = "code"
        elif state == "block_comment":
            output[index] = " "
            if char == "/" and nxt == "*":
                output[index + 1] = " "
                index += 1
                block_depth += 1
            elif char == "*" and nxt == "/":
                output[index + 1] = " "
                index += 1
                block_depth -= 1
                if block_depth == 0:
                    state = "code"
        index += 1
    if state in {"single", "double", "bracket", "block_comment"}:
        raise ValueError("unterminated SQL literal or comment")
    return "".join(output)


def validate_single_statement(sql: str) -> str:
    if not sql.strip():
        raise ValueError("SQL is empty")
    masked = mask_literals_and_comments(sql).strip()
    if masked.endswith(";"):
        masked = masked[:-1].rstrip()
    if not masked:
        raise ValueError("SQL is empty")
    if ";" in masked:
        raise ValueError("multiple SQL statements are not allowed")
    return masked


def validate_readonly_sql(sql: str) -> str:
    masked = validate_single_statement(sql)
    match = re.match(r"([A-Za-z]+)", masked)
    first = match.group(1).upper() if match else ""
    if first not in ALLOWED_READ_FIRST:
        raise ValueError(f"statement {first or '<unknown>'} is not allowed in read-only mode")
    tokens = {token.upper() for token in re.findall(r"\b[A-Za-z]+\b", masked)}
    blocked = sorted(tokens & FORBIDDEN_READ_TOKENS)
    if blocked:
        raise ValueError(f"write/administrative keyword is not allowed: {blocked[0]}")
    return sql


def ensure_write_allowed(confirm_write: bool) -> None:
    if not env_bool("MSSQL_ALLOW_WRITE", False):
        raise ValueError("write mode is disabled; set MSSQL_ALLOW_WRITE=true and retry with --confirm-write")
    if not confirm_write:
        raise ValueError("write mode requires --confirm-write")


def read_value(value: str) -> str:
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def read_params(value: str | None) -> list[Any] | dict[str, Any] | None:
    if value is None:
        return None
    parsed = json.loads(read_value(value))
    if not isinstance(parsed, (list, dict)):
        raise ValueError("--params must be a JSON array or object")
    return parsed


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


def rows_payload(rows: list[dict[str, Any]], truncated: bool = False, affected_rows: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"rows": rows, "row_count": len(rows)}
    if truncated:
        payload["truncated"] = True
    if affected_rows is not None:
        payload["affected_rows"] = affected_rows
    return payload


def build_connect_kwargs(args: argparse.Namespace, *, read_only: bool) -> dict[str, Any]:
    if pymssql is None:
        raise RuntimeError("pymssql is not installed; run with: uv run --python 3.13 --with pymssql python ...")
    if not args.host:
        raise ValueError("missing MSSQL host: set MSSQL_HOST or pass --host")
    if not args.database:
        raise ValueError("missing MSSQL database: set MSSQL_DATABASE or pass --database")
    if not args.user:
        raise ValueError("missing MSSQL user: set MSSQL_USER or pass --user")
    password = os.environ.get("MSSQL_PASSWORD", "")
    if password == "":
        raise ValueError("missing MSSQL_PASSWORD environment variable")
    kwargs: dict[str, Any] = {
        "server": args.host,
        "port": str(args.port),
        "user": args.user,
        "password": password,
        "database": args.database,
        "login_timeout": args.connect_timeout,
        "timeout": args.timeout,
        "charset": args.charset,
        "appname": args.appname,
        "autocommit": False,
        "read_only": read_only,
        "encryption": args.encryption,
        "use_datetime2": True,
    }
    if args.tds_version:
        kwargs["tds_version"] = args.tds_version
    return kwargs


def open_connection(args: argparse.Namespace, *, read_only: bool) -> Any:
    return pymssql.connect(**build_connect_kwargs(args, read_only=read_only))


def cursor_rows(cursor: Any, max_rows: int) -> tuple[list[dict[str, Any]], bool]:
    fetched = cursor.fetchmany(max_rows + 1)
    truncated = len(fetched) > max_rows
    rows = fetched[:max_rows]
    normalized = [{str(key): jsonable(value) for key, value in row.items()} for row in rows]
    return normalized, truncated


def execute_sql(cursor: Any, sql: str, params: list[Any] | dict[str, Any] | None) -> None:
    if params is None:
        cursor.execute(sql)
    else:
        cursor.execute(sql, params)


def run_query(args: argparse.Namespace, sql: str, params: list[Any] | dict[str, Any] | None) -> dict[str, Any]:
    connection = open_connection(args, read_only=True)
    try:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(f"SET LOCK_TIMEOUT {args.timeout * 1000}")
        cursor.execute(f"SET ROWCOUNT {args.max_rows + 1}")
        execute_sql(cursor, sql, params)
        rows, truncated = cursor_rows(cursor, args.max_rows)
        return rows_payload(rows, truncated)
    finally:
        connection.close()


def run_exec(args: argparse.Namespace, sql: str, params: list[Any] | dict[str, Any] | None) -> dict[str, Any]:
    ensure_write_allowed(args.confirm_write)
    validate_single_statement(sql)
    connection = open_connection(args, read_only=False)
    try:
        cursor = connection.cursor(as_dict=True)
        cursor.execute(f"SET LOCK_TIMEOUT {args.timeout * 1000}")
        execute_sql(cursor, sql, params)
        if cursor.description:
            rows, truncated = cursor_rows(cursor, args.max_rows)
            connection.commit()
            payload = rows_payload(rows, truncated, cursor.rowcount)
            payload["ok"] = True
            return payload
        connection.commit()
        return {"ok": True, "affected_rows": cursor.rowcount}
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="ms.py", description="generic MSSQL JSON CLI with guarded read mode")
    command.add_argument("--host", default=os.environ.get("MSSQL_HOST"))
    command.add_argument("--port", type=int, default=int(os.environ.get("MSSQL_PORT", "1433")))
    command.add_argument("--database", default=os.environ.get("MSSQL_DATABASE"))
    command.add_argument("--user", default=os.environ.get("MSSQL_USER"))
    command.add_argument("--encryption", choices=ENCRYPTION_CHOICES, default=os.environ.get("MSSQL_ENCRYPTION", "require"))
    command.add_argument("--tds-version", default=os.environ.get("MSSQL_TDS_VERSION"))
    command.add_argument("--appname", default=os.environ.get("MSSQL_APPNAME", "mssql-safe"))
    command.add_argument("--charset", default="UTF-8")
    command.add_argument("--connect-timeout", type=int, default=10)
    command.add_argument("--timeout", type=int, default=60)
    command.add_argument("--max-rows", type=int, default=10_000)
    subcommands = command.add_subparsers(dest="command", required=True)

    query = subcommands.add_parser("query", help="run guarded read-only SQL")
    query.add_argument("--sql", required=True, help="literal SQL, @file.sql, or - for stdin")
    query.add_argument("--params", help="JSON array/object, @file.json, or - for stdin")

    subcommands.add_parser("list-databases", help="list databases")
    subcommands.add_parser("list-schemas", help="list schemas")

    tables = subcommands.add_parser("list-tables", help="list tables and views")
    tables.add_argument("--schema")

    describe = subcommands.add_parser("describe-table", help="describe one table or view")
    describe.add_argument("--schema", default="dbo")
    describe.add_argument("--table", required=True)

    exec_command = subcommands.add_parser("exec", help="run one controlled DDL/DML statement")
    exec_command.add_argument("--confirm-write", action="store_true")
    exec_command.add_argument("--sql", required=True, help="literal SQL, @file.sql, or - for stdin")
    exec_command.add_argument("--params", help="JSON array/object, @file.json, or - for stdin")
    return command


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "query":
        return run_query(args, validate_readonly_sql(read_value(args.sql)), read_params(args.params))
    if args.command == "list-databases":
        return run_query(args, "SELECT name, database_id, create_date FROM sys.databases ORDER BY name", None)
    if args.command == "list-schemas":
        return run_query(args, "SELECT name AS schema_name, schema_id FROM sys.schemas ORDER BY name", None)
    if args.command == "list-tables":
        if args.schema:
            sql = (
                "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_SCHEMA = %s ORDER BY TABLE_SCHEMA, TABLE_NAME"
            )
            params: list[Any] | dict[str, Any] | None = [args.schema]
        else:
            sql = "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES ORDER BY TABLE_SCHEMA, TABLE_NAME"
            params = None
        return run_query(args, sql, params)
    if args.command == "describe-table":
        sql = (
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT, CHARACTER_MAXIMUM_LENGTH, "
            "NUMERIC_PRECISION, NUMERIC_SCALE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION"
        )
        return run_query(args, sql, [args.schema, args.table])
    return run_exec(args, read_value(args.sql), read_params(args.params))


def main() -> None:
    try:
        result = dispatch(parser().parse_args())
        sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError, RuntimeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except Exception as error:
        print(f"MSSQL command failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
