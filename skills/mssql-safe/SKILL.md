---
name: mssql-safe
description: Query or cautiously execute Microsoft SQL Server through a JSON CLI. Use when the user explicitly asks for MSSQL or SQL Server querying or schema inspection. Connection details come only from standard environment variables or explicit non-secret flags.
compatibility: Python 3.11+, uv, network access to Microsoft SQL Server, and pymssql. Use a server-side read-only login for read commands; server permissions remain the real boundary.
license: MIT
metadata:
  author: bgevorkian
  version: "1.0.0"
---

# MSSQL Safe

Generic Microsoft SQL Server skill with UTF-8 JSON output, read-only query guards, timeout and row limits, and an intentionally gated `exec` command.

## Configuration

Use standard environment variables or global flags:

| Variable | Flag | Default |
|---|---|---|
| `MSSQL_HOST` | `--host` | none |
| `MSSQL_PORT` | `--port` | `1433` |
| `MSSQL_DATABASE` | `--database` | none |
| `MSSQL_USER` | `--user` | none |
| `MSSQL_PASSWORD` | none | empty |
| `MSSQL_ENCRYPTION` | `--encryption` | `require` |
| `MSSQL_TDS_VERSION` | `--tds-version` | driver default |
| `MSSQL_APPNAME` | `--appname` | `mssql-safe` |
| `MSSQL_ALLOW_WRITE` | none | `false` |

`MSSQL_ENCRYPTION` accepts `default`, `off`, `request`, or `require`.

Never pass a password as a CLI argument. Inject `MSSQL_PASSWORD` from a secret manager.

## Secret setup

Before configuring credentials, ask which secret manager and local profile the user wants. Follow [Secure secret profiles](https://github.com/bgevorkian/agent-skills/blob/main/docs/secure-secrets.md). Do not invent or publish profile names, hosts, templates, or secret references. If the user asks for the author's method, use a per-profile Proton Pass pointer file with process-scoped `pass-cli run`. Never request or display resolved values.

## Run

From this skill directory:

```bash
uv run --python 3.13 --with pymssql python scripts/ms.py query --sql "SELECT @@VERSION AS version"
uv run --python 3.13 --with pymssql python scripts/ms.py query --sql @report.sql --params '[42, "active"]'
uv run --python 3.13 --with pymssql python scripts/ms.py list-databases
uv run --python 3.13 --with pymssql python scripts/ms.py list-schemas
uv run --python 3.13 --with pymssql python scripts/ms.py list-tables --schema dbo
uv run --python 3.13 --with pymssql python scripts/ms.py describe-table --schema dbo --table users
```

Global flags go before the subcommand:

```bash
uv run --python 3.13 --with pymssql python scripts/ms.py \
  --host db.example.net --database app --user app_reader --encryption require \
  query --sql "SELECT TOP 10 * FROM dbo.users"
```

`--sql` accepts a literal string, `@file.sql`, or `-` for stdin. `--params` accepts a JSON array or object, also from `@file.json` or stdin.

## Controlled write mode

`exec` is disabled unless both checks pass:

1. environment variable `MSSQL_ALLOW_WRITE=true`
2. CLI flag `--confirm-write`

Example:

```bash
MSSQL_ALLOW_WRITE=true uv run --python 3.13 --with pymssql python scripts/ms.py \
  --host db.example.net --database app --user app_writer \
  exec --confirm-write --sql "UPDATE dbo.jobs SET status = 'done' WHERE id = 42"
```

Server permissions are the real authorization boundary. The client gate is only defense in depth.

## Safety contract

- Read commands allow only obvious read-only statements such as `SELECT`, `WITH`, and `VALUES`.
- Multiple statements and obvious DDL, DML, and administrative keywords are rejected for read commands.
- Read commands connect with SQL Server read-only intent, set a lock timeout, and cap fetched rows.
- `exec` rejects empty or multi-statement input and never runs unless both write gates are enabled.
- Do not print secrets, connection strings, or environment variables.
- Ask before touching sensitive datasets, even for read-only work.

## Output

Successful commands return JSON:

```json
{
  "rows": [{"name": "master"}],
  "row_count": 1
}
```

Binary values are hex encoded. Dates, times, decimals, UUIDs, lists, and dictionaries are converted to JSON-safe values.

## Tests

```bash
uv run --python 3.13 --with pymssql python tests/test_ms.py
```
