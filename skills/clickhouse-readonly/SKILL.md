---
name: clickhouse-readonly
description: Run safe read-only ClickHouse SQL, list databases/tables, and inspect table schemas through a JSON CLI. Use when the user explicitly asks to query or inspect ClickHouse. Connections are configured only through CLI flags or CLICKHOUSE_* environment variables; no hosts or credentials are bundled.
compatibility: Python 3.11+, uv, network access to a ClickHouse HTTP(S) endpoint, and clickhouse-connect. Credentials should belong to a server-side read-only user.
license: MIT
metadata:
  author: bgevorkian
  version: "1.0.0"
---

# ClickHouse Read-only

Generic, infrastructure-neutral ClickHouse query skill. The helper emits UTF-8 JSON, applies an obvious-write guard, sends ClickHouse `readonly=1`, and limits execution time/result rows.

## Configuration

Set connection values in the environment; never put secrets in `SKILL.md`, shell history, or committed files.

| Variable | Required | Default |
|---|---:|---|
| `CLICKHOUSE_HOST` | yes (or `--host`) | none |
| `CLICKHOUSE_PORT` | no | client default |
| `CLICKHOUSE_USER` | no | `default` |
| `CLICKHOUSE_PASSWORD` | no | empty |
| `CLICKHOUSE_DATABASE` | no | server default |
| `CLICKHOUSE_SECURE` | no | `true` |
| `CLICKHOUSE_VERIFY` | no | `true` |

Prefer a secret manager that injects environment variables for one process.

## Secret setup

Before configuring credentials, ask which secret manager and local profile the user wants. Follow [Secure secret profiles](https://github.com/bgevorkian/agent-skills/blob/main/docs/secure-secrets.md). Do not invent or publish profile names, hosts, templates, or secret references. If the user asks for the author's method, use a per-profile Proton Pass pointer file with process-scoped `pass-cli run`. Never request or display resolved values.

## Run

From this skill directory:

```bash
uv run --python 3.13 --with clickhouse-connect python scripts/ch.py list-databases
uv run --python 3.13 --with clickhouse-connect python scripts/ch.py list-tables --database analytics
uv run --python 3.13 --with clickhouse-connect python scripts/ch.py describe-table --database analytics --table events
uv run --python 3.13 --with clickhouse-connect python scripts/ch.py query --sql "SELECT count() AS n FROM analytics.events"
uv run --python 3.13 --with clickhouse-connect python scripts/ch.py query --sql @query.sql --params '{"day":"2026-01-01"}'
```

`--sql` accepts a literal string, `@file.sql`, or `-` for stdin. Named ClickHouse parameters use `{name:Type}` and values from `--params` JSON.

Global options go before the command:

```bash
... scripts/ch.py --host localhost --port 8123 --no-secure query --sql "SELECT version()"
```

Use `--help` for all options.

## Safety contract

- Only `SELECT`, `WITH`, `SHOW`, `DESCRIBE`, `DESC`, `EXPLAIN`, and `EXISTS` statements pass the local guard.
- Multiple statements and obvious mutation/DDL keywords are rejected.
- Every request sends server settings `readonly=1`, `max_execution_time`, and `max_result_rows`.
- The database account must also be read-only. Client-side checks are defense in depth, not an authorization boundary.
- TLS certificate verification is enabled by default. Disable it only for a trusted local development endpoint.
- Do not print environment variables or connection secrets.
- Ask before querying sensitive or regulated datasets even when the query itself is read-only.

## Output

Successful commands return a JSON object:

```json
{
  "rows": [{"n": 42}],
  "row_count": 1
}
```

Failures use a non-zero exit code and a concise message on stderr. Binary values are hex encoded; dates, decimals, and UUIDs are JSON-safe.

## Tests

```bash
uv run --python 3.13 --with clickhouse-connect python tests/test_ch.py
```
