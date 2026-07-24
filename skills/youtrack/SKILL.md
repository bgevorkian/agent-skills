---
name: youtrack
description: Read and selectively write YouTrack issues, comments, projects, users, custom-field schema, and knowledge-base articles through a UTF-8 JSON REST CLI. Use when the user explicitly asks about YouTrack and you need generic, self-hosted access configured only by environment variables.
compatibility: Python 3.11+, uv, network access to a YouTrack server, and environment variables YOUTRACK_URL and YOUTRACK_TOKEN. Optional defaults: YOUTRACK_PROJECT and YOUTRACK_ALLOW_WRITE.
license: MIT
metadata:
  author: bgevorkian
  version: "1.0.0"
---

# YouTrack

Generic YouTrack REST JSON CLI with stdlib HTTP only. Reads cover the current user, projects, users, issues, comments, custom-field schema, and knowledge-base articles. Writes are intentionally gated.

## Configuration

Set environment variables outside shell history and committed files.

| Variable | Required | Default |
|---|---:|---|
| `YOUTRACK_URL` | yes (or `--url`) | none |
| `YOUTRACK_TOKEN` | yes | none |
| `YOUTRACK_PROJECT` | no | used as default `--project` |
| `YOUTRACK_ALLOW_WRITE` | no | `false` |

Use a token with the minimum scope needed. Never print or paste the token.

## Run

From this skill directory:

```bash
uv run --python 3.13 python scripts/yt.py me
uv run --python 3.13 python scripts/yt.py projects --query Demo
uv run --python 3.13 python scripts/yt.py users --query alice
uv run --python 3.13 python scripts/yt.py issues --query "project: DEMO State: Open" --top 20
uv run --python 3.13 python scripts/yt.py issue DEMO-123
uv run --python 3.13 python scripts/yt.py comments DEMO-123
uv run --python 3.13 python scripts/yt.py fields --project DEMO
uv run --python 3.13 python scripts/yt.py articles --query "project: DEMO"
uv run --python 3.13 python scripts/yt.py article DEMO-A-1
```

Pass `--url https://youtrack.example.net` to override `YOUTRACK_URL` for one run.

## Write gate

Every mutation requires both of these:

1. `YOUTRACK_ALLOW_WRITE=true`
2. explicit `--confirm-write`

Without both, create/update/comment/article mutations fail locally before any request is sent.

## Reads

| Command | Purpose |
|---|---|
| `me` | current user |
| `projects --query Q [--top N] [--skip N]` | list/search projects |
| `users --query Q [--top N] [--skip N]` | list/search users |
| `issues --query Q [--top N] [--skip N]` | issue search |
| `issue ID` | one issue |
| `comments ID [--top N] [--skip N]` | issue comments |
| `fields --project KEY [--top N] [--skip N]` | project custom-field schema |
| `articles --query Q [--top N] [--skip N]` | article search |
| `article ID` | one article with content |

`KEY` can be a project short name or internal id. Output is UTF-8 JSON.

## Controlled writes

```bash
YOUTRACK_ALLOW_WRITE=true \
uv run --python 3.13 python scripts/yt.py --confirm-write create \
  --project DEMO \
  --summary "Add generic YouTrack skill" \
  --description @body.md

YOUTRACK_ALLOW_WRITE=true \
uv run --python 3.13 python scripts/yt.py --confirm-write update DEMO-123 \
  --summary "Updated title"

YOUTRACK_ALLOW_WRITE=true \
uv run --python 3.13 python scripts/yt.py --confirm-write comment DEMO-123 \
  --text "Done."

YOUTRACK_ALLOW_WRITE=true \
uv run --python 3.13 python scripts/yt.py --confirm-write article-create \
  --project DEMO \
  --summary "Runbook" \
  --content @article.md

YOUTRACK_ALLOW_WRITE=true \
uv run --python 3.13 python scripts/yt.py --confirm-write article-update DEMO-A-1 \
  --content @article.md
```

`--description`, `--text`, `--content`, and `--custom-fields` accept a literal string, `@file`, or `-` for stdin.

## Field discovery and selectors

Before creating an issue, inspect the project schema instead of hardcoding internal field values:

```bash
uv run --python 3.13 python scripts/yt.py fields --project DEMO
uv run --python 3.13 python scripts/yt.py users --query alice
```

`create --custom-fields` and `update --custom-fields` accept either raw YouTrack `customFields` JSON or selector objects that resolve against the live schema and user search results. For selector-based updates, pass `--project` or set `YOUTRACK_PROJECT`.

Example selectors:

```json
[
  {"name": "Priority", "$byName": "Critical"},
  {"name": "Assignee", "$user": "alice"},
  {"name": "Tags", "$byNames": ["api", "docs"]}
]
```

The CLI converts these to REST payloads using project field schema and user lookup, so agents can discover valid options first and avoid hardcoded ids.

## Safety and behavior

- Uses Python stdlib `urllib`; no MCP and no third-party HTTP client.
- Uses UTF-8 JSON for stdin, files, stdout, and request bodies.
- Read commands support pagination with `--top` and `--skip`.
- Helpful HTTP errors include status and server message when available.
- The token is read from `YOUTRACK_TOKEN` and is never printed.
- Keep `--top` bounded; the CLI rejects oversized page sizes.

## Tests

```bash
uv run --python 3.13 python tests/test_yt.py
```
