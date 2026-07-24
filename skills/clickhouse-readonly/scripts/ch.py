from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import clickhouse_connect

ALLOWED_FIRST = {"SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "EXISTS"}
FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE",
    "RENAME", "OPTIMIZE", "KILL", "GRANT", "REVOKE", "ATTACH", "DETACH",
}


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise SystemExit(f"{name} must be true or false")


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
            elif char == "'" and (index == 0 or sql[index - 1] != "\\"):
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


def read_params(value: str | None) -> dict[str, Any] | None:
    if value is None:
        return None
    raw = read_value(value)
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("--params must be a JSON object")
    return parsed


def jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
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


def result_payload(result: Any) -> dict[str, Any]:
    columns = result.column_names
    rows = [{column: jsonable(value) for column, value in zip(columns, row)} for row in result.result_rows]
    return {"rows": rows, "row_count": len(rows)}


def make_client(args: argparse.Namespace) -> Any:
    if not args.host:
        raise ValueError("missing ClickHouse host: set CLICKHOUSE_HOST or pass --host")
    kwargs: dict[str, Any] = {
        "host": args.host,
        "username": args.user,
        "password": os.environ.get("CLICKHOUSE_PASSWORD", ""),
        "secure": args.secure,
        "verify": args.verify,
        "connect_timeout": args.connect_timeout,
    }
    if args.port is not None:
        kwargs["port"] = args.port
    if args.database:
        kwargs["database"] = args.database
    return clickhouse_connect.get_client(**kwargs)


def query_settings(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "readonly": 1,
        "max_execution_time": args.timeout,
        "max_result_rows": args.max_rows,
        "result_overflow_mode": "break",
    }


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="ch.py", description="generic read-only ClickHouse JSON CLI")
    command.add_argument("--host", default=os.environ.get("CLICKHOUSE_HOST"))
    port = os.environ.get("CLICKHOUSE_PORT")
    command.add_argument("--port", type=int, default=int(port) if port else None)
    command.add_argument("--user", default=os.environ.get("CLICKHOUSE_USER", "default"))
    command.add_argument("--database", default=os.environ.get("CLICKHOUSE_DATABASE"))
    command.add_argument("--secure", action=argparse.BooleanOptionalAction, default=env_bool("CLICKHOUSE_SECURE", True))
    command.add_argument("--verify", action=argparse.BooleanOptionalAction, default=env_bool("CLICKHOUSE_VERIFY", True))
    command.add_argument("--connect-timeout", type=int, default=10)
    command.add_argument("--timeout", type=int, default=60)
    command.add_argument("--max-rows", type=int, default=10_000)
    subcommands = command.add_subparsers(dest="command", required=True)

    query = subcommands.add_parser("query", help="run guarded read-only SQL")
    query.add_argument("--sql", required=True, help="literal SQL, @file.sql, or - for stdin")
    query.add_argument("--params", help="JSON object, @file.json, or - for stdin")

    subcommands.add_parser("list-databases", help="list databases")
    tables = subcommands.add_parser("list-tables", help="list tables in a database")
    tables.add_argument("--database", required=True, dest="target_database")
    describe = subcommands.add_parser("describe-table", help="list columns and types")
    describe.add_argument("--database", required=True, dest="target_database")
    describe.add_argument("--table", required=True)
    return command


def run(args: argparse.Namespace) -> dict[str, Any]:
    client = make_client(args)
    settings = query_settings(args)
    try:
        if args.command == "query":
            sql = validate_readonly_sql(read_value(args.sql))
            result = client.query(sql, parameters=read_params(args.params), settings=settings)
        elif args.command == "list-databases":
            result = client.query("SHOW DATABASES", settings=settings)
        elif args.command == "list-tables":
            result = client.query(
                "SELECT name, engine, total_rows FROM system.tables "
                "WHERE database = {database:String} ORDER BY name",
                parameters={"database": args.target_database}, settings=settings,
            )
        else:
            result = client.query(
                "SELECT name, type, default_kind, default_expression, comment "
                "FROM system.columns WHERE database = {database:String} AND table = {table:String} "
                "ORDER BY position",
                parameters={"database": args.target_database, "table": args.table}, settings=settings,
            )
        return result_payload(result)
    finally:
        client.close()


def main() -> None:
    try:
        payload = run(parser().parse_args())
        sys.stdout.buffer.write((json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except Exception as error:
        print(f"ClickHouse query failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
