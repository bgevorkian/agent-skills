---
name: trino-readonly
description: Query and inspect Trino through a guarded JSON CLI. Use when the user explicitly asks for Trino or Iceberg querying or schema inspection. Connection details come only from standard environment variables or explicit non-secret flags.
compatibility: Python 3.11+, uv, network access to Trino, and the trino Python client. Use a server-side read-only account in addition to the client safeguards.
license: MIT
metadata:
  author: bgevorkian
  version: "1.0.0"
---

# Trino Read-only

Generic Trino skill with UTF-8 JSON output, obvious-write guards, single-statement enforcement, request timeouts, and bounded result fetching.

## Configuration

Use standard environment variables or global flags:

| Variable | Flag | Default |
|---|---|---|
| `TRINO_HOST` | `--host` | none |
| `TRINO_PORT` | `--port` | `443` for `https`, otherwise `8080` |
| `TRINO_USER` | `--user` | none |
| `TRINO_CATALOG` | `--catalog` | none |
| `TRINO_SCHEMA` | `--schema` | none |
| `TRINO_HTTP_SCHEME` | `--http-scheme` | `https` |
| `TRINO_PASSWORD` | none | empty |
| `TRINO_ACCESS_TOKEN` | none | empty |
| `TRINO_CERT` | none | empty |
| `TRINO_KEY` | none | empty |
| `TRINO_VERIFY` | `--verify/--no-verify` | `true` |
| `TRINO_CA_BUNDLE` | `--ca-bundle` | none |

Authentication options:

- `TRINO_PASSWORD` → basic auth
- `TRINO_ACCESS_TOKEN` → bearer token auth
- `TRINO_CERT` + `TRINO_KEY` → client certificate auth
- none of the above → no auth

Never pass secrets as CLI arguments.

## Secret setup

Before configuring credentials, ask which secret manager and local profile the user wants. Follow [Secure secret profiles](https://github.com/bgevorkian/agent-skills/blob/main/docs/secure-secrets.md). Do not invent or publish profile names, hosts, templates, or secret references. If the user asks for the author's method, use a per-profile Proton Pass pointer file with process-scoped `pass-cli run`. Never request or display resolved values.

## Run

From this skill directory:

```bash
uv run --python 3.13 --with trino python scripts/tr.py list-catalogs
uv run --python 3.13 --with trino python scripts/tr.py list-schemas --catalog iceberg
uv run --python 3.13 --with trino python scripts/tr.py list-tables --catalog iceberg --schema analytics
uv run --python 3.13 --with trino python scripts/tr.py describe-table --catalog iceberg --schema analytics --table events
uv run --python 3.13 --with trino python scripts/tr.py query --sql "SELECT current_catalog, current_schema"
uv run --python 3.13 --with trino python scripts/tr.py query --sql @report.sql
```

Global flags go before the subcommand:

```bash
uv run --python 3.13 --with trino python scripts/tr.py \
  --host trino.example.net --user analyst --catalog iceberg --schema analytics \
  query --sql "SELECT * FROM events LIMIT 10"
```

`--sql` accepts a literal string, `@file.sql`, or `-` for stdin.

## Safety contract

- Read mode allows only obvious read-only statements such as `SELECT`, `WITH`, `SHOW`, `DESCRIBE`, `DESC`, `EXPLAIN`, `VALUES`, and `TABLE`.
- Multiple statements and obvious DDL, DML, transaction, and session-changing keywords are rejected.
- Request timeout and TLS verification are enabled by default; fetched rows are capped and marked as truncated when necessary.
- There is no write command in this skill.
- Use a read-only server-side account. Client checks are defense in depth, not an authorization boundary.
- Do not print secrets, tokens, certificates, or environment variables.

## Output

Successful commands return JSON:

```json
{
  "rows": [{"catalog": "iceberg"}],
  "row_count": 1
}
```

Dates, times, decimals, UUIDs, binary values, lists, and dictionaries are converted to JSON-safe values.

## Tests

```bash
uv run --python 3.13 --with trino python tests/test_tr.py
```
