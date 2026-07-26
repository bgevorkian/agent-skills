#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ipaddress
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any, Callable

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
MAX_LIMIT = 500
MAX_RESPONSE_BYTES = 1_000_000
ERROR_BODY_BYTES = 4_096
WRITE_ENV_NAME = "PREFECT_ALLOW_WRITE"
WRITE_ENV_VALUE = "true"
INSECURE_HTTP_ENV_NAME = "PREFECT_ALLOW_INSECURE_HTTP"
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


class CliError(Exception):
    pass


def url_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return scheme, (parsed.hostname or "").lower(), parsed.port or default_port


class BearerRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, api_key: str, allow_insecure_http: bool = False) -> None:
        self.api_key = api_key
        self.allow_insecure_http = allow_insecure_http

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if self.api_key and url_origin(req.full_url) != url_origin(target):
            raise CliError("refusing to follow bearer-token redirect to a different origin")
        require_safe_bearer_transport(target, self.api_key, self.allow_insecure_http)
        return super().redirect_request(req, fp, code, msg, headers, target)


class PrefectClient:
    def __init__(
        self,
        api_url: str,
        api_key: str = "",
        timeout: int = DEFAULT_TIMEOUT,
        opener: Callable[..., Any] | None = None,
        allow_insecure_http: bool = False,
    ) -> None:
        self.api_url = api_url.rstrip("/")
        require_safe_bearer_transport(self.api_url, api_key, allow_insecure_http)
        self.api_key = api_key
        self.timeout = timeout
        self.opener = opener or urllib.request.build_opener(
            BearerRedirectHandler(api_key, allow_insecure_http)
        ).open

    def request(
        self,
        method: str,
        path: str,
        body: Any | None = None,
        *,
        allow_not_found: bool = False,
    ) -> Any | None:
        url = f"{self.api_url}{path}"
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Accept", "application/json")
        if body is not None:
            request.add_header("Content-Type", "application/json")
        if self.api_key:
            request.add_header("Authorization", f"Bearer {self.api_key}")
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            if allow_not_found and error.code == 404:
                return None
            raise CliError(
                f"HTTP {error.code} {method} {path}: {extract_http_error_detail(error)}"
            ) from None
        except urllib.error.URLError as error:
            raise CliError(f"connection error {method} {path}: {error.reason}") from None
        except TimeoutError:
            raise CliError(f"timeout {method} {path}") from None

        if len(raw) > MAX_RESPONSE_BYTES:
            raise CliError(f"response too large for {method} {path}")
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise CliError(f"invalid JSON from {method} {path}: {error.msg}") from None


def extract_http_error_detail(error: urllib.error.HTTPError) -> str:
    raw = error.read(ERROR_BODY_BYTES).decode("utf-8", errors="replace").strip()
    if not raw:
        return error.reason or "request failed"
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return shorten(raw)
    if isinstance(payload, dict):
        for key in ("detail", "message", "error", "exception_detail", "reason"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return shorten(value.strip())
        return shorten(json.dumps(payload, ensure_ascii=False))
    if isinstance(payload, str) and payload.strip():
        return shorten(payload.strip())
    return shorten(json.dumps(payload, ensure_ascii=False))


def shorten(text: str, limit: int = 300) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def require_safe_bearer_transport(
    api_url: str,
    api_key: str,
    allow_insecure_http: bool = False,
) -> None:
    parsed = urllib.parse.urlsplit(api_url)
    if not api_key or parsed.scheme.lower() == "https":
        return
    hostname = parsed.hostname or ""
    local = hostname == "localhost" or hostname.endswith(".localhost")
    try:
        local = local or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        pass
    if local or allow_insecure_http:
        return
    raise CliError(
        "refusing to send PREFECT_API_KEY over remote plaintext HTTP; use HTTPS, "
        f"localhost, or explicitly set {INSECURE_HTTP_ENV_NAME}=true"
    )


def bounded_int(value: int | None, default: int) -> int:
    if value is None:
        value = default
    if value < 1 or value > MAX_LIMIT:
        raise CliError(f"limit must be between 1 and {MAX_LIMIT}")
    return value


def bounded_timeout(value: int | None) -> int:
    if value is None:
        return DEFAULT_TIMEOUT
    if value < 1 or value > MAX_TIMEOUT:
        raise CliError(f"timeout must be between 1 and {MAX_TIMEOUT} seconds")
    return value


def resolve_api_url(args: argparse.Namespace, env: dict[str, str]) -> str:
    api_url = args.api_url or env.get("PREFECT_API_URL", "")
    if not api_url:
        raise CliError("missing Prefect API URL; pass --api-url or set PREFECT_API_URL")
    return api_url.rstrip("/")


def resolve_api_key(args: argparse.Namespace, env: dict[str, str]) -> str:
    del args
    return env.get("PREFECT_API_KEY", "")


def parse_json_value(value: str) -> Any:
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def read_json_source(source: str) -> Any:
    text = source
    if source.startswith("@"):
        with open(source[1:], encoding="utf-8") as handle:
            text = handle.read()
    return json.loads(text)


def parse_params(args: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if getattr(args, "params", None):
        payload = read_json_source(args.params)
        if not isinstance(payload, dict):
            raise CliError("--params must be a JSON object")
        params.update(payload)
    for item in getattr(args, "param", None) or []:
        if "=" not in item:
            raise CliError(f"bad --param {item!r}; expected key=value")
        key, value = item.split("=", 1)
        if not key:
            raise CliError("parameter name cannot be empty")
        params[key] = parse_json_value(value)
    return params


def ensure_write_allowed(args: argparse.Namespace, env: dict[str, str]) -> None:
    if env.get(WRITE_ENV_NAME) != WRITE_ENV_VALUE:
        raise CliError(
            f"write blocked: set {WRITE_ENV_NAME}={WRITE_ENV_VALUE} and pass --confirm-write"
        )
    if not getattr(args, "confirm_write", False):
        raise CliError(
            f"write blocked: set {WRITE_ENV_NAME}={WRITE_ENV_VALUE} and pass --confirm-write"
        )


def is_uuid(value: str) -> bool:
    return bool(UUID_RE.fullmatch(value))


def encode_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def slim_flow_run(item: dict[str, Any]) -> dict[str, Any]:
    state = item.get("state") or {}
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "deployment_id": item.get("deployment_id"),
        "state": state.get("type"),
        "state_name": state.get("name"),
        "start_time": item.get("start_time"),
        "end_time": item.get("end_time"),
        "total_run_time": item.get("total_run_time"),
    }


def resolve_deployment(client: PrefectClient, selector: str) -> dict[str, Any]:
    if is_uuid(selector):
        response = client.request("GET", f"/deployments/{selector}")
        if not isinstance(response, dict):
            raise CliError("unexpected deployment response")
        return response
    if "/" in selector:
        flow_name, deployment_name = selector.split("/", 1)
        if not flow_name or not deployment_name:
            raise CliError("deployment selector flow/deployment must include both names")
        response = client.request(
            "GET",
            f"/deployments/name/{encode_path(flow_name)}/{encode_path(deployment_name)}",
        )
        if not isinstance(response, dict):
            raise CliError("unexpected deployment response")
        return response
    response = client.request(
        "POST",
        "/deployments/filter",
        {"deployments": {"name": {"any_": [selector]}}, "limit": 2},
    )
    if not isinstance(response, list):
        raise CliError("unexpected deployment lookup response")
    if not response:
        raise CliError(f"no deployment named {selector!r}")
    if len(response) > 1:
        raise CliError(
            f"deployment name {selector!r} is ambiguous; use flow/deployment or a UUID"
        )
    item = response[0]
    if not isinstance(item, dict):
        raise CliError("unexpected deployment response")
    return item


def command_flow_runs(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    body: dict[str, Any] = {"limit": bounded_int(args.limit, 20), "sort": "START_TIME_DESC"}
    filters: dict[str, Any] = {}
    if args.state:
        filters.setdefault("flow_runs", {})["state"] = {
            "type": {"any_": [value.upper() for value in args.state]}
        }
    if args.deployment:
        deployment = resolve_deployment(client, args.deployment)
        filters.setdefault("flow_runs", {})["deployment_id"] = {"any_": [deployment["id"]]}
    if args.since_hours is not None:
        if args.since_hours < 1:
            raise CliError("--since-hours must be at least 1")
        after = datetime.now(timezone.utc).timestamp() - args.since_hours * 3600
        filters.setdefault("flow_runs", {})["start_time"] = {
            "after_": datetime.fromtimestamp(after, tz=timezone.utc).isoformat()
        }
    body.update(filters)
    response = client.request("POST", "/flow_runs/filter", body)
    if not isinstance(response, list):
        raise CliError("unexpected flow-runs response")
    items = response if args.full else [slim_flow_run(item) for item in response if isinstance(item, dict)]
    return {"items": items, "count": len(items)}


def command_flow_run(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request("GET", f"/flow_runs/{args.id}")
    if not isinstance(response, dict):
        raise CliError("unexpected flow-run response")
    return response


def command_task_runs(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    body = {
        "task_runs": {"flow_run_id": {"any_": [args.flow_run]}},
        "limit": bounded_int(args.limit, 200),
        "sort": "EXPECTED_START_TIME_DESC",
    }
    response = client.request("POST", "/task_runs/filter", body)
    if not isinstance(response, list):
        raise CliError("unexpected task-runs response")
    if args.full:
        return {"items": response, "count": len(response)}
    items = []
    for item in response:
        if not isinstance(item, dict):
            continue
        state = item.get("state") or {}
        items.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "state": state.get("type"),
                "state_name": state.get("name"),
                "start_time": item.get("start_time"),
                "end_time": item.get("end_time"),
            }
        )
    return {"items": items, "count": len(items)}


def command_logs(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    if not args.flow_run and not args.task_run:
        raise CliError("logs requires --flow-run or --task-run")
    filters: dict[str, Any] = {}
    if args.flow_run:
        filters["flow_run_id"] = {"any_": [args.flow_run]}
    if args.task_run:
        filters["task_run_id"] = {"any_": [args.task_run]}
    response = client.request(
        "POST",
        "/logs/filter",
        {"logs": filters, "limit": bounded_int(args.limit, 200), "sort": "TIMESTAMP_ASC"},
    )
    if not isinstance(response, list):
        raise CliError("unexpected logs response")
    if args.full:
        return {"items": response, "count": len(response)}
    items = []
    for item in response:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "timestamp": item.get("timestamp"),
                "level": item.get("level"),
                "message": item.get("message"),
            }
        )
    return {"items": items, "count": len(items)}


def command_deployments(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request(
        "POST", "/deployments/filter", {"limit": bounded_int(args.limit, 200)}
    )
    if not isinstance(response, list):
        raise CliError("unexpected deployments response")
    if args.full:
        return {"items": response, "count": len(response)}
    items = []
    for item in sorted(
        (entry for entry in response if isinstance(entry, dict)),
        key=lambda value: str(value.get("name", "")),
    ):
        items.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "paused": item.get("paused"),
                "status": item.get("status"),
                "work_pool": item.get("work_pool_name"),
                "schedules": len(item.get("schedules") or []),
            }
        )
    return {"items": items, "count": len(items)}


def command_deployment(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    return resolve_deployment(client, args.deployment)


def command_schedules(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    deployment = resolve_deployment(client, args.deployment)
    response = client.request("GET", f"/deployments/{deployment['id']}/schedules")
    if not isinstance(response, list):
        raise CliError("unexpected schedules response")
    if args.full:
        return {"items": response, "count": len(response)}
    items = []
    for item in response:
        if not isinstance(item, dict):
            continue
        schedule = item.get("schedule") or {}
        items.append(
            {
                "id": item.get("id"),
                "active": item.get("active"),
                "cron": schedule.get("cron"),
                "timezone": schedule.get("timezone"),
            }
        )
    return {"items": items, "count": len(items)}


def command_scheduled_runs(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    deployment = resolve_deployment(client, args.deployment)
    response = client.request(
        "POST",
        "/deployments/get_scheduled_flow_runs",
        {"deployment_ids": [deployment["id"]], "limit": bounded_int(args.limit, 20)},
    )
    if not isinstance(response, list):
        raise CliError("unexpected scheduled-runs response")
    items = response if args.full else [slim_flow_run(item) for item in response if isinstance(item, dict)]
    return {"items": items, "count": len(items)}


def command_variables(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request(
        "POST", "/variables/filter", {"limit": bounded_int(args.limit, 100)}
    )
    if not isinstance(response, list):
        raise CliError("unexpected variables response")
    if args.full:
        return {"items": response, "count": len(response)}
    items = []
    for item in response:
        if not isinstance(item, dict):
            continue
        items.append(
            {
                "name": item.get("name"),
                "value": item.get("value"),
                "tags": item.get("tags"),
            }
        )
    return {"items": items, "count": len(items)}


def command_variable(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request("GET", f"/variables/name/{encode_path(args.name)}")
    if not isinstance(response, dict):
        raise CliError("unexpected variable response")
    return response


def command_automations(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request(
        "POST", "/automations/filter", {"limit": bounded_int(args.limit, 100)}
    )
    if not isinstance(response, list):
        raise CliError("unexpected automations response")
    if args.full:
        return {"items": response, "count": len(response)}
    items = []
    for item in response:
        if not isinstance(item, dict):
            continue
        trigger = item.get("trigger") or {}
        actions = item.get("actions") or []
        items.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "enabled": item.get("enabled"),
                "trigger": trigger.get("type"),
                "actions": [action.get("type") for action in actions if isinstance(action, dict)],
            }
        )
    return {"items": items, "count": len(items)}


def command_automation(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request("GET", f"/automations/{args.id}")
    if not isinstance(response, dict):
        raise CliError("unexpected automation response")
    return response


def command_work_pools(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request(
        "POST", "/work_pools/filter", {"limit": bounded_int(args.limit, 50)}
    )
    if not isinstance(response, list):
        raise CliError("unexpected work-pools response")
    return {"items": response, "count": len(response)}


def command_server_version(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request("GET", "/admin/version")
    if isinstance(response, dict) and "version" in response:
        return {"version": response["version"]}
    return {"version": response}


def command_run(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    deployment = resolve_deployment(client, args.deployment)
    body: dict[str, Any] = {"parameters": parse_params(args)}
    if args.name:
        body["name"] = args.name
    response = client.request(
        "POST", f"/deployments/{deployment['id']}/create_flow_run", body
    )
    if not isinstance(response, dict):
        raise CliError("unexpected run response")
    state = response.get("state") or {}
    return {
        "created_flow_run": response.get("id"),
        "name": response.get("name"),
        "state": state.get("type"),
        "deployment": deployment.get("name"),
    }


def command_cancel(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request(
        "POST",
        f"/flow_runs/{args.id}/set_state",
        {"state": {"type": "CANCELLING", "name": "Cancelling"}, "force": args.force},
    )
    if not isinstance(response, dict):
        raise CliError("unexpected cancel response")
    return response


def command_retry(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    response = client.request(
        "POST",
        f"/flow_runs/{args.id}/set_state",
        {
            "state": {
                "type": "SCHEDULED",
                "name": "AwaitingRetry",
                "state_details": {"scheduled_time": now_iso()},
            },
            "force": True,
        },
    )
    if not isinstance(response, dict):
        raise CliError("unexpected retry response")
    return response


def command_delete(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    client.request("DELETE", f"/flow_runs/{args.id}")
    return {"deleted_flow_run": args.id}


def command_pause(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    deployment = resolve_deployment(client, args.deployment)
    client.request("PATCH", f"/deployments/{deployment['id']}", {"paused": True})
    return {"deployment": deployment.get("name"), "paused": True}


def command_resume(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    deployment = resolve_deployment(client, args.deployment)
    client.request("PATCH", f"/deployments/{deployment['id']}", {"paused": False})
    return {"deployment": deployment.get("name"), "paused": False}


def command_set_state(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    state: dict[str, Any] = {"type": args.type.upper()}
    if args.state_name:
        state["name"] = args.state_name
    if args.message:
        state["message"] = args.message
    response = client.request(
        "POST", f"/flow_runs/{args.id}/set_state", {"state": state, "force": args.force}
    )
    if not isinstance(response, dict):
        raise CliError("unexpected set-state response")
    return response


def command_variable_set(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    value = parse_json_value(args.value)
    existing = client.request(
        "GET", f"/variables/name/{encode_path(args.name)}", allow_not_found=True
    )
    if existing is None:
        client.request("POST", "/variables/", {"name": args.name, "value": value})
        return {"created_variable": args.name, "value": value}
    client.request("PATCH", f"/variables/name/{encode_path(args.name)}", {"value": value})
    return {"updated_variable": args.name, "value": value}


def command_variable_delete(args: argparse.Namespace, client: PrefectClient) -> dict[str, Any]:
    client.request("DELETE", f"/variables/name/{encode_path(args.name)}")
    return {"deleted_variable": args.name}


READ_COMMANDS = {
    "flow-runs",
    "flow-run",
    "task-runs",
    "logs",
    "deployments",
    "deployment",
    "schedules",
    "scheduled-runs",
    "variables",
    "variable",
    "automations",
    "automation",
    "work-pools",
    "server-version",
}

WRITE_COMMANDS = {
    "run",
    "cancel",
    "retry",
    "delete",
    "pause",
    "resume",
    "set-state",
    "variable-set",
    "variable-delete",
}


def add_write_gate(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--confirm-write",
        action="store_true",
        help=f"required for writes together with {WRITE_ENV_NAME}={WRITE_ENV_VALUE}",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pf.py", description="Prefect 3 REST JSON CLI")
    parser.add_argument("--api-url", help="Prefect API base URL")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT, help="HTTP timeout in seconds")
    subparsers = parser.add_subparsers(dest="command", required=True)

    flow_runs = subparsers.add_parser("flow-runs", help="list flow runs")
    flow_runs.add_argument("--limit", type=int, default=20)
    flow_runs.add_argument("--state", nargs="*")
    flow_runs.add_argument("--deployment")
    flow_runs.add_argument("--since-hours", type=int)
    flow_runs.add_argument("--full", action="store_true")
    flow_runs.set_defaults(func=command_flow_runs)

    flow_run = subparsers.add_parser("flow-run", help="get one flow run")
    flow_run.add_argument("--id", required=True)
    flow_run.set_defaults(func=command_flow_run)

    task_runs = subparsers.add_parser("task-runs", help="list task runs for a flow run")
    task_runs.add_argument("--flow-run", required=True)
    task_runs.add_argument("--limit", type=int, default=200)
    task_runs.add_argument("--full", action="store_true")
    task_runs.set_defaults(func=command_task_runs)

    logs = subparsers.add_parser("logs", help="list logs")
    logs.add_argument("--flow-run")
    logs.add_argument("--task-run")
    logs.add_argument("--limit", type=int, default=200)
    logs.add_argument("--full", action="store_true")
    logs.set_defaults(func=command_logs)

    deployments = subparsers.add_parser("deployments", help="list deployments")
    deployments.add_argument("--limit", type=int, default=200)
    deployments.add_argument("--full", action="store_true")
    deployments.set_defaults(func=command_deployments)

    deployment = subparsers.add_parser("deployment", help="get one deployment")
    deployment.add_argument("--deployment", required=True)
    deployment.set_defaults(func=command_deployment)

    schedules = subparsers.add_parser("schedules", help="list deployment schedules")
    schedules.add_argument("--deployment", required=True)
    schedules.add_argument("--full", action="store_true")
    schedules.set_defaults(func=command_schedules)

    scheduled_runs = subparsers.add_parser(
        "scheduled-runs", aliases=["scheduled"], help="list scheduled runs for a deployment"
    )
    scheduled_runs.add_argument("--deployment", required=True)
    scheduled_runs.add_argument("--limit", type=int, default=20)
    scheduled_runs.add_argument("--full", action="store_true")
    scheduled_runs.set_defaults(func=command_scheduled_runs)

    variables = subparsers.add_parser("variables", help="list variables")
    variables.add_argument("--limit", type=int, default=100)
    variables.add_argument("--full", action="store_true")
    variables.set_defaults(func=command_variables)

    variable = subparsers.add_parser("variable", help="get one variable")
    variable.add_argument("--name", required=True)
    variable.set_defaults(func=command_variable)

    automations = subparsers.add_parser("automations", help="list automations")
    automations.add_argument("--limit", type=int, default=100)
    automations.add_argument("--full", action="store_true")
    automations.set_defaults(func=command_automations)

    automation = subparsers.add_parser("automation", help="get one automation")
    automation.add_argument("--id", required=True)
    automation.set_defaults(func=command_automation)

    work_pools = subparsers.add_parser("work-pools", help="list work pools")
    work_pools.add_argument("--limit", type=int, default=50)
    work_pools.set_defaults(func=command_work_pools)

    version = subparsers.add_parser("server-version", help="get server version")
    version.set_defaults(func=command_server_version)

    run = subparsers.add_parser("run", help="create a flow run from a deployment")
    run.add_argument("--deployment", required=True)
    run.add_argument("--param", action="append", help="key=value; value is JSON if parseable")
    run.add_argument("--params", help="JSON object or @file.json")
    run.add_argument("--name")
    add_write_gate(run)
    run.set_defaults(func=command_run)

    cancel = subparsers.add_parser("cancel", help="cancel a flow run")
    cancel.add_argument("--id", required=True)
    cancel.add_argument("--force", action="store_true")
    add_write_gate(cancel)
    cancel.set_defaults(func=command_cancel)

    retry = subparsers.add_parser("retry", help="retry a flow run")
    retry.add_argument("--id", required=True)
    add_write_gate(retry)
    retry.set_defaults(func=command_retry)

    delete = subparsers.add_parser("delete", help="delete a flow run")
    delete.add_argument("--id", required=True)
    add_write_gate(delete)
    delete.set_defaults(func=command_delete)

    pause = subparsers.add_parser("pause", help="pause a deployment")
    pause.add_argument("--deployment", required=True)
    add_write_gate(pause)
    pause.set_defaults(func=command_pause)

    resume = subparsers.add_parser("resume", help="resume a deployment")
    resume.add_argument("--deployment", required=True)
    add_write_gate(resume)
    resume.set_defaults(func=command_resume)

    set_state = subparsers.add_parser("set-state", help="set a flow run state")
    set_state.add_argument("--id", required=True)
    set_state.add_argument("--type", required=True)
    set_state.add_argument("--state-name")
    set_state.add_argument("--message")
    set_state.add_argument("--force", action="store_true")
    add_write_gate(set_state)
    set_state.set_defaults(func=command_set_state)

    variable_set = subparsers.add_parser("variable-set", help="create or update a variable")
    variable_set.add_argument("--name", required=True)
    variable_set.add_argument("--value", required=True)
    add_write_gate(variable_set)
    variable_set.set_defaults(func=command_variable_set)

    variable_delete = subparsers.add_parser("variable-delete", help="delete a variable")
    variable_delete.add_argument("--name", required=True)
    add_write_gate(variable_delete)
    variable_delete.set_defaults(func=command_variable_delete)

    return parser


def execute(
    argv: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
    client: PrefectClient | None = None,
) -> Any:
    env = dict(os.environ if env is None else env)
    args = build_parser().parse_args(argv)
    timeout = bounded_timeout(args.timeout)
    if client is None:
        client = PrefectClient(
            api_url=resolve_api_url(args, env),
            api_key=resolve_api_key(args, env),
            timeout=timeout,
            allow_insecure_http=env.get(INSECURE_HTTP_ENV_NAME) == "true",
        )
    if args.command in WRITE_COMMANDS:
        ensure_write_allowed(args, env)
    return args.func(args, client)


def main(
    argv: list[str] | None = None,
    *,
    env: dict[str, str] | None = None,
    stdout: io.TextIOBase | None = None,
    stderr: io.TextIOBase | None = None,
) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    try:
        result = execute(argv, env=env)
    except CliError as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str), file=stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
