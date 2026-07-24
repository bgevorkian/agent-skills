from __future__ import annotations

import argparse
import asyncio
import getpass
import json
import os
import re
import ssl
import sys
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

ALLOWED_FIRST = {"SELECT", "WITH", "SHOW", "EXPLAIN", "VALUES", "TABLE"}
FORBIDDEN = {
    "INSERT", "UPDATE", "DELETE", "MERGE", "CREATE", "ALTER", "DROP", "TRUNCATE",
    "REINDEX", "CLUSTER", "VACUUM", "ANALYZE", "COPY", "CALL", "DO", "GRANT", "REVOKE",
    "COMMENT", "SECURITY", "REFRESH", "LISTEN", "NOTIFY", "UNLISTEN", "LOCK", "SET", "RESET",
}


def mask_literals_and_comments(sql: str) -> str:
    output = list(sql)
    index = 0
    state = "code"
    dollar_tag = ""
    block_depth = 0
    while index < len(sql):
        char = sql[index]
        nxt = sql[index + 1] if index + 1 < len(sql) else ""
        if state == "code":
            dollar = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", sql[index:])
            if dollar:
                dollar_tag = dollar.group(0)
                for offset in range(len(dollar_tag)):
                    output[index + offset] = " "
                index += len(dollar_tag) - 1
                state = "dollar"
            elif char == "'":
                output[index] = " "
                state = "single"
            elif char == '"':
                output[index] = " "
                state = "double"
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
        elif state == "dollar":
            if sql.startswith(dollar_tag, index):
                for offset in range(len(dollar_tag)):
                    output[index + offset] = " "
                index += len(dollar_tag) - 1
                state = "code"
            else:
                output[index] = " "
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
    if state in {"single", "double", "dollar", "block_comment"}:
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


def read_params(value: str | None) -> list[Any]:
    if value is None:
        return []
    parsed = json.loads(read_value(value))
    if not isinstance(parsed, list):
        raise ValueError("--params must be a JSON array")
    return parsed


def read_hosts(value: str) -> list[str]:
    if value.startswith("@"):
        hosts = [line.strip() for line in Path(value[1:]).read_text(encoding="utf-8").splitlines()]
    else:
        hosts = [item.strip() for item in value.split(",")]
    result = list(dict.fromkeys(host for host in hosts if host))
    if not result:
        raise ValueError("host list is empty")
    return result


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


def ssl_option(mode: str) -> ssl.SSLContext | bool:
    if mode == "disable":
        return False
    if mode == "require":
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        return context
    context = ssl.create_default_context(cafile=os.environ.get("PGSSLROOTCERT"))
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    return context


def connection_kwargs(args: argparse.Namespace, host_override: str | None = None) -> dict[str, Any]:
    if args.dsn and host_override:
        raise ValueError("query-many cannot combine --dsn/DATABASE_URL with --hosts")
    kwargs: dict[str, Any] = {
        "timeout": args.connect_timeout,
        "ssl": ssl_option(args.ssl_mode),
    }
    if args.dsn:
        kwargs["dsn"] = args.dsn
        return kwargs
    host = host_override or args.host
    if not host:
        raise ValueError("missing PostgreSQL host: set PGHOST, DATABASE_URL, or pass --host")
    if not args.database:
        raise ValueError("missing database: set PGDATABASE or pass --database")
    kwargs.update({
        "host": host,
        "port": args.port,
        "database": args.database,
        "user": args.user,
        "password": os.environ.get("PGPASSWORD", ""),
    })
    return kwargs


def payload(records: list[Any], truncated: bool = False) -> dict[str, Any]:
    rows = [{str(key): jsonable(value) for key, value in dict(record).items()} for record in records]
    result: dict[str, Any] = {"rows": rows, "row_count": len(rows)}
    if truncated:
        result["truncated"] = True
    return result


async def run_query(args: argparse.Namespace, sql: str, params: list[Any], host: str | None = None) -> dict[str, Any]:
    connection = await asyncpg.connect(**connection_kwargs(args, host))
    try:
        records: list[Any] = []
        truncated = False
        async with connection.transaction(readonly=True):
            await connection.execute("SELECT set_config('statement_timeout', $1, true)", str(args.timeout * 1000))
            if args.search_path:
                await connection.execute("SELECT set_config('search_path', $1, true)", args.search_path)
            async for record in connection.cursor(sql, *params, prefetch=min(args.max_rows + 1, 1_000)):
                if len(records) >= args.max_rows:
                    truncated = True
                    break
                records.append(record)
        return payload(records, truncated)
    finally:
        await connection.close()


async def run_many(args: argparse.Namespace, sql: str, params: list[Any], hosts: list[str]) -> dict[str, Any]:
    if not 1 <= args.max_parallel <= 20:
        raise ValueError("--max-parallel must be between 1 and 20")
    semaphore = asyncio.Semaphore(args.max_parallel)

    async def one(host: str) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            try:
                return host, await run_query(args, sql, params, host)
            except Exception as error:
                return host, {"error": f"{type(error).__name__}: {error}"}

    pairs = await asyncio.gather(*(one(host) for host in hosts))
    return dict(pairs)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="pg.py", description="generic read-only PostgreSQL JSON CLI")
    command.add_argument("--dsn", default=os.environ.get("DATABASE_URL"))
    command.add_argument("--host", default=os.environ.get("PGHOST"))
    command.add_argument("--port", type=int, default=int(os.environ.get("PGPORT", "5432")))
    command.add_argument("--database", default=os.environ.get("PGDATABASE"))
    command.add_argument("--user", default=os.environ.get("PGUSER", getpass.getuser()))
    command.add_argument("--ssl-mode", choices=["disable", "require", "verify-full"], default=os.environ.get("PGSSLMODE", "require"))
    command.add_argument("--connect-timeout", type=int, default=10)
    command.add_argument("--timeout", type=int, default=60)
    command.add_argument("--max-rows", type=int, default=10_000)
    command.add_argument("--search-path")
    subcommands = command.add_subparsers(dest="command", required=True)

    query = subcommands.add_parser("query", help="run guarded read-only SQL")
    query.add_argument("--sql", required=True, help="literal SQL, @file.sql, or - for stdin")
    query.add_argument("--params", help="JSON array, @file.json, or - for stdin")

    many = subcommands.add_parser("query-many", help="fan out the same query across hosts")
    many.add_argument("--hosts", required=True, help="comma-separated hosts or @hosts.txt")
    many.add_argument("--sql", required=True, help="literal SQL, @file.sql, or - for stdin")
    many.add_argument("--params", help="JSON array or @file.json")
    many.add_argument("--max-parallel", type=int, default=10)

    subcommands.add_parser("list-schemas", help="list non-system schemas")
    tables = subcommands.add_parser("list-tables", help="list tables and views")
    tables.add_argument("--schema", default="public")
    describe = subcommands.add_parser("describe-table", help="list table columns")
    describe.add_argument("--schema", default="public")
    describe.add_argument("--table", required=True)
    return command


async def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "query":
        return await run_query(args, validate_readonly_sql(read_value(args.sql)), read_params(args.params))
    if args.command == "query-many":
        if args.dsn:
            raise ValueError("query-many requires individual connection settings, not DATABASE_URL/--dsn")
        sql = validate_readonly_sql(read_value(args.sql))
        return await run_many(args, sql, read_params(args.params), read_hosts(args.hosts))
    if args.command == "list-schemas":
        sql = "SELECT schema_name FROM information_schema.schemata WHERE schema_name NOT LIKE 'pg_%' AND schema_name <> 'information_schema' ORDER BY schema_name"
        return await run_query(args, sql, [])
    if args.command == "list-tables":
        sql = "SELECT table_name, table_type FROM information_schema.tables WHERE table_schema = $1 ORDER BY table_name"
        return await run_query(args, sql, [args.schema])
    sql = "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_schema = $1 AND table_name = $2 ORDER BY ordinal_position"
    return await run_query(args, sql, [args.schema, args.table])


def main() -> None:
    try:
        result = asyncio.run(dispatch(parser().parse_args()))
        sys.stdout.buffer.write((json.dumps(result, ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except Exception as error:
        print(f"PostgreSQL query failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
