---
name: postgres-readonly
description: Run safe read-only PostgreSQL SQL against one host or fan out the same query across multiple hosts, returning UTF-8 JSON. Use when the user explicitly asks to query or inspect PostgreSQL/Postgres. Connections use standard PG* environment variables, DATABASE_URL, or explicit non-secret flags; no hosts or credentials are bundled.
compatibility: Python 3.11+, uv, network access to PostgreSQL, and asyncpg. Use a server-side read-only role in addition to the client safeguards.
license: MIT
metadata:
  author: bgevorkian
  version: "1.0.0"
---

# PostgreSQL Read-only

Generic PostgreSQL JSON CLI for a single database or bounded parallel fan-out. It validates obvious writes and executes every query inside a read-only transaction.

## Configuration

Use `DATABASE_URL` / `--dsn` or standard PostgreSQL environment variables:

| Variable | Flag | Default |
|---|---|---|
| `PGHOST` | `--host` | none |
| `PGPORT` | `--port` | `5432` |
| `PGDATABASE` | `--database` | none |
| `PGUSER` | `--user` | operating-system user |
| `PGPASSWORD` | none | empty |
| `PGSSLMODE` | `--ssl-mode` | `require` |
| `DATABASE_URL` | `--dsn` | none |

Never pass a password as a CLI argument. Inject `PGPASSWORD` with a secret manager.

## Secret setup

Before configuring credentials, ask which secret manager and local profile the user wants. Follow [Secure secret profiles](https://github.com/bgevorkian/agent-skills/blob/main/docs/secure-secrets.md). Do not invent or publish profile names, hosts, templates, or secret references. If the user asks for the author's method, use a per-profile Proton Pass pointer file with process-scoped `pass-cli run`. Never request or display resolved values.

## Run

From this skill directory:

```bash
uv run --python 3.13 --with asyncpg python scripts/pg.py query --sql "SELECT current_database(), now()"
uv run --python 3.13 --with asyncpg python scripts/pg.py query --sql @report.sql --params '[42, "active"]'
uv run --python 3.13 --with asyncpg python scripts/pg.py query-many --hosts db-a.example.net,db-b.example.net --sql @health.sql
uv run --python 3.13 --with asyncpg python scripts/pg.py list-schemas
uv run --python 3.13 --with asyncpg python scripts/pg.py list-tables --schema public
uv run --python 3.13 --with asyncpg python scripts/pg.py describe-table --schema public --table users
```

`--sql` accepts literal SQL, `@file.sql`, or `-` for stdin. `--params` is a JSON array for PostgreSQL `$1`, `$2`, … placeholders.

For global connection flags, place them before the command:

```bash
... scripts/pg.py --host localhost --database app --ssl-mode disable query --sql "SELECT 1"
```

## Fan-out

`query-many` accepts comma-separated hosts or `@hosts.txt` and runs with bounded concurrency (`--max-parallel`, default 10, maximum 20). Each host returns either rows or a structured error, so one unavailable host does not discard successful results.

`query-many` intentionally does not accept a DSN because replacing hosts inside arbitrary DSNs is ambiguous. Use the individual connection flags/environment variables.

## Safety contract

- The local guard allows only `SELECT`, `WITH`, `SHOW`, `EXPLAIN`, `VALUES`, and `TABLE`.
- Multiple statements and obvious DDL/DML/administrative keywords are rejected.
- Every query runs inside `transaction(readonly=True)` with a statement timeout.
- Use a database role with server-side read-only privileges. Client checks are not an authorization boundary.
- TLS is required by default. `verify-full` validates certificates and hostnames; `disable` should be limited to trusted local development.
- Do not print environment variables, DSNs, or passwords.
- Ask before accessing sensitive or regulated datasets.

## Output

Single-host commands:

```json
{
  "rows": [{"current_database": "app"}],
  "row_count": 1
}
```

Fan-out:

```json
{
  "db-a.example.net": {"rows": [{"ok": 1}], "row_count": 1},
  "db-b.example.net": {"error": "connection failed"}
}
```

Dates, decimals, UUIDs, JSON values, arrays, and binary values are converted safely.

## Tests

```bash
uv run --python 3.13 --with asyncpg python tests/test_pg.py
```
