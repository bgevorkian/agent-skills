---
name: prefect-ops
description: Inspect and manage a Prefect 3 API from a safe JSON CLI. Use when the user explicitly asks to read Prefect runs, deployments, logs, variables, automations, work pools, or to perform a confirmed operational change such as running a deployment or cancelling a flow run.
compatibility: Python 3.11+, uv, network access to a Prefect 3 API endpoint, and optional bearer-token authentication.
license: MIT
metadata:
  author: bgevorkian
  version: "1.0.0"
---

# Prefect Ops

Generic Prefect 3 REST skill. The helper uses only the Python standard library, prints UTF-8 JSON to stdout, avoids echoing secrets, and keeps reads and writes clearly separated.

## Configuration

Provide the API endpoint through an environment variable or flag:

| Variable | Flag | Required | Notes |
|---|---|---:|---|
| `PREFECT_API_URL` | `--api-url` | yes | Prefect API base URL, for example `https://prefect.example/api` |
| `PREFECT_API_KEY` | none | no | Optional bearer token; environment-only to avoid shell history/process-list exposure |
| `PREFECT_ALLOW_WRITE` | none | for writes only | Must be exactly `true` to enable mutations |

Writes require **both**:

1. `PREFECT_ALLOW_WRITE=true`
2. `--confirm-write`

Reads never require either gate.

## Secret setup

Before configuring credentials, ask which secret manager and local profile the user wants. Follow [Secure secret profiles](https://github.com/bgevorkian/agent-skills/blob/main/docs/secure-secrets.md). Do not invent or publish profile names, hosts, templates, or secret references. If the user asks for the author's method, use a per-profile Proton Pass pointer file with process-scoped `pass-cli run`. Never request or display resolved values.

## Run

From this skill directory:

```bash
uv run --python 3.13 python scripts/pf.py --api-url https://prefect.example/api server-version
uv run --python 3.13 python scripts/pf.py flow-runs --limit 20
uv run --python 3.13 python scripts/pf.py deployments --limit 50
uv run --python 3.13 python scripts/pf.py deployment --deployment my-flow/my-deployment
uv run --python 3.13 python scripts/pf.py logs --flow-run 00000000-0000-0000-0000-000000000000 --limit 100
uv run --python 3.13 python scripts/pf.py scheduled-runs --deployment my-deployment --limit 10
uv run --python 3.13 python scripts/pf.py variables --limit 100
```

Write examples:

```bash
PREFECT_ALLOW_WRITE=true uv run --python 3.13 python scripts/pf.py run --deployment my-flow/my-deployment --param retries=2 --confirm-write
PREFECT_ALLOW_WRITE=true uv run --python 3.13 python scripts/pf.py cancel --id 00000000-0000-0000-0000-000000000000 --confirm-write
PREFECT_ALLOW_WRITE=true uv run --python 3.13 python scripts/pf.py pause --deployment my-flow/my-deployment --confirm-write
PREFECT_ALLOW_WRITE=true uv run --python 3.13 python scripts/pf.py variable-set --name feature_flag --value true --confirm-write
```

`--deployment` accepts:

- a deployment UUID
- `flow_name/deployment_name`
- a bare deployment name, if it resolves to exactly one deployment

## Read commands

- `flow-runs`
- `flow-run`
- `task-runs`
- `logs`
- `deployments`
- `deployment`
- `schedules`
- `scheduled-runs`
- `variables`
- `variable`
- `automations`
- `automation`
- `work-pools`
- `server-version`

## Write commands

- `run`
- `cancel`
- `retry`
- `delete`
- `pause`
- `resume`
- `set-state`
- `variable-set`
- `variable-delete`

## Safety contract

- API keys are never printed.
- Every write is double-gated by environment and CLI confirmation.
- Response sizes, timeouts, and list limits are bounded.
- HTTP failures return concise JSON errors on stderr.
- Deployment lookup is generic and contains no bundled names or infrastructure assumptions.
- Prefer a server-side read-only or least-privilege token when possible.

## Tests

From the repository root:

```bash
uv run --python 3.13 python skills/prefect-ops/tests/test_pf.py
uv run --python 3.13 scripts/validate_skills.py
```
