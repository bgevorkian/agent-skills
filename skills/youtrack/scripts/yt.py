from __future__ import annotations

import argparse
import ipaddress
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

DEFAULT_TIMEOUT = 30
DEFAULT_TOP = 50
MAX_TOP = 1_000

ISSUE_FIELDS = (
    "id,idReadable,summary,description,created,updated,resolved,"
    "reporter(id,login,fullName),assignee(id,login,fullName),"
    "customFields(name,value(id,name,login,fullName,text,presentation))"
)
COMMENT_FIELDS = "id,text,created,updated,author(id,login,fullName)"
PROJECT_FIELDS = "id,name,shortName,archived"
USER_FIELDS = "id,login,fullName,email"
FIELD_SCHEMA_FIELDS = (
    "id,canBeEmpty,emptyFieldText,field(id,name,localizedName,"
    "fieldType(id,presentation)),bundle(id,values(id,name,localizedName,presentation,text))"
)
ARTICLE_FIELDS = "id,idReadable,summary,updated,parentArticle(id,idReadable,summary)"
ARTICLE_GET_FIELDS = "id,idReadable,summary,content,updated,parentArticle(id,idReadable,summary)"
SELECTOR_KEYS = {"$byName", "$byNames", "$user", "$users"}


class CliError(Exception):
    pass


class HttpFailure(CliError):
    pass


def url_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlsplit(url)
    scheme = parsed.scheme.lower()
    default_port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return scheme, (parsed.hostname or "").lower(), parsed.port or default_port


class BearerRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, token: str) -> None:
        self.token = token

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if self.token and url_origin(req.full_url) != url_origin(target):
            raise CliError("refusing to follow bearer-token redirect to a different origin")
        require_safe_bearer_transport(target, self.token)
        return super().redirect_request(req, fp, code, msg, headers, target)


class YouTrackClient:
    def __init__(self, base_url: str, token: str, timeout: int = DEFAULT_TIMEOUT, opener=None):
        self.base_url = normalize_base_url(base_url)
        require_safe_bearer_transport(self.base_url, token)
        self.token = token
        self.timeout = timeout
        self.opener = opener or urllib.request.build_opener(BearerRedirectHandler(token)).open
        self._project_cache: dict[str, str] = {}
        self._field_cache: dict[str, list[dict[str, Any]]] = {}
        self._user_cache: dict[str, dict[str, Any]] = {}

    def request(self, method: str, path: str, params: dict[str, Any] | None = None,
                body: Any = None) -> Any:
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        request = urllib.request.Request(
            build_api_url(self.base_url, path, params),
            data=data,
            headers=headers,
            method=method,
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise HttpFailure(format_http_error(error)) from error
        except urllib.error.URLError as error:
            raise HttpFailure(f"request failed: {error.reason}") from error
        return parse_json_response(raw)

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self.request("GET", path, params=params)

    def post(self, path: str, body: Any = None, params: dict[str, Any] | None = None) -> Any:
        return self.request("POST", path, params=params, body=body)

    def projects(self, query: str | None = None, fields: str = PROJECT_FIELDS,
                 top: int = DEFAULT_TOP, skip: int = 0) -> Any:
        return self.get("admin/projects", {
            "query": query,
            "fields": fields,
            "$top": top,
            "$skip": skip,
        })

    def users(self, query: str, fields: str = USER_FIELDS,
              top: int = DEFAULT_TOP, skip: int = 0) -> Any:
        return self.get("users", {
            "query": query,
            "fields": fields,
            "$top": top,
            "$skip": skip,
        })

    def resolve_project_id(self, selector: str) -> str:
        cached = self._project_cache.get(selector)
        if cached:
            return cached
        if re.fullmatch(r"\d+-\d+", selector):
            self._project_cache[selector] = selector
            return selector
        projects = self.projects(query=selector, fields="id,name,shortName", top=100, skip=0)
        if not isinstance(projects, list):
            raise CliError("projects response must be a list")
        project = choose_match(projects, selector, keys=("id", "shortName", "name"), kind="project")
        project_id = str(project["id"])
        self._project_cache[selector] = project_id
        short_name = project.get("shortName")
        if short_name:
            self._project_cache[str(short_name)] = project_id
        name = project.get("name")
        if name:
            self._project_cache[str(name)] = project_id
        return project_id

    def project_fields(self, project_selector: str) -> list[dict[str, Any]]:
        project_id = self.resolve_project_id(project_selector)
        cached = self._field_cache.get(project_id)
        if cached is not None:
            return cached
        rows = self.get(f"admin/projects/{project_id}/customFields", {
            "fields": FIELD_SCHEMA_FIELDS,
            "$top": MAX_TOP,
            "$skip": 0,
        })
        if not isinstance(rows, list):
            raise CliError("field schema response must be a list")
        self._field_cache[project_id] = rows
        return rows

    def resolve_user(self, selector: str) -> dict[str, Any]:
        cached = self._user_cache.get(selector)
        if cached:
            return cached
        rows = self.users(selector, fields="id,login,fullName", top=50, skip=0)
        if not isinstance(rows, list):
            raise CliError("users response must be a list")
        user = choose_match(rows, selector, keys=("id", "login", "fullName"), kind="user")
        result = {"id": str(user["id"])}
        self._user_cache[selector] = result
        login = user.get("login")
        if login:
            self._user_cache[str(login)] = result
        full_name = user.get("fullName")
        if full_name:
            self._user_cache[str(full_name)] = result
        return result


def env_bool(name: str, default: bool = False) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise CliError(f"{name} must be true or false")


def normalize_base_url(value: str) -> str:
    base = value.strip().rstrip("/")
    if not base:
        raise CliError("missing YouTrack base URL")
    if not re.match(r"^https?://", base, re.IGNORECASE):
        raise CliError("YouTrack base URL must start with http:// or https://")
    return base


def require_safe_bearer_transport(base_url: str, token: str) -> None:
    if not token or urllib.parse.urlsplit(base_url).scheme.lower() == "https":
        return
    hostname = urllib.parse.urlsplit(base_url).hostname or ""
    local = hostname == "localhost" or hostname.endswith(".localhost")
    try:
        local = local or ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        pass
    if local or env_bool("YOUTRACK_ALLOW_INSECURE_HTTP", False):
        return
    raise CliError(
        "refusing to send YOUTRACK_TOKEN over remote plaintext HTTP; use HTTPS, "
        "localhost, or explicitly set YOUTRACK_ALLOW_INSECURE_HTTP=true"
    )


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise CliError(f"missing {name}")
    return value


def parse_json_response(raw: str) -> Any:
    if not raw.strip():
        return None
    return json.loads(raw)


def build_api_url(base_url: str, path: str, params: dict[str, Any] | None = None) -> str:
    base = normalize_base_url(base_url)
    path = path.lstrip("/")
    url = f"{base}/api/{path}"
    if not params:
        return url
    query = urllib.parse.urlencode(
        [(key, value) for key, value in params.items() if value is not None],
        doseq=True,
    )
    return f"{url}?{query}" if query else url


def read_value(value: str | None) -> str | None:
    if value is None:
        return None
    if value == "-":
        return sys.stdin.read()
    if value.startswith("@"):
        return Path(value[1:]).read_text(encoding="utf-8")
    return value


def read_json_arg(value: str | None, *, expected: type | tuple[type, ...] | None = None) -> Any:
    raw = read_value(value)
    if raw is None:
        return None
    data = json.loads(raw)
    if expected is not None and not isinstance(data, expected):
        names = expected.__name__ if isinstance(expected, type) else "/".join(t.__name__ for t in expected)
        raise CliError(f"expected JSON {names}")
    return data


def jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value


def emit(payload: Any) -> None:
    sys.stdout.buffer.write((json.dumps(jsonable(payload), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))


def format_http_error(error: urllib.error.HTTPError) -> str:
    body = ""
    try:
        body = error.read().decode("utf-8", errors="replace")
    except Exception:
        body = ""
    detail = body.strip()
    if detail:
        try:
            parsed = json.loads(detail)
        except json.JSONDecodeError:
            pass
        else:
            detail = extract_http_detail(parsed)
    label = getattr(error, "reason", None) or error.msg or "HTTP error"
    return f"HTTP {error.code} {label}: {detail}" if detail else f"HTTP {error.code} {label}"


def extract_http_detail(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("error", "error_description", "message"):
            item = value.get(key)
            if isinstance(item, str) and item.strip():
                return item.strip()
        if "error" in value and isinstance(value["error"], dict):
            nested = extract_http_detail(value["error"])
            if nested:
                return nested
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def ensure_top(value: int) -> int:
    if value < 0:
        raise CliError("--top must be non-negative")
    if value > MAX_TOP:
        raise CliError(f"--top must be <= {MAX_TOP}")
    return value


def ensure_skip(value: int) -> int:
    if value < 0:
        raise CliError("--skip must be non-negative")
    return value


def choose_match(rows: list[dict[str, Any]], selector: str, *, keys: tuple[str, ...], kind: str) -> dict[str, Any]:
    if not rows:
        raise CliError(f"{kind} {selector!r} not found")
    exact: list[dict[str, Any]] = []
    normalized_selector = selector.strip().casefold()
    for row in rows:
        for key in keys:
            candidate = row.get(key)
            if isinstance(candidate, str) and candidate.strip().casefold() == normalized_selector:
                exact.append(row)
                break
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise CliError(f"{kind} selector {selector!r} is ambiguous")
    if len(rows) == 1:
        return rows[0]
    preview = ", ".join(match_preview(row, keys) for row in rows[:5])
    raise CliError(f"{kind} selector {selector!r} is ambiguous: {preview}")


def match_preview(row: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key)
        if isinstance(value, str) and value:
            return value
    return json.dumps(row, ensure_ascii=False)


def custom_fields_need_schema(custom_fields: list[dict[str, Any]] | None) -> bool:
    return bool(
        custom_fields and
        any(isinstance(item, dict) and any(key in item for key in SELECTOR_KEYS) for item in custom_fields)
    )


def resolve_custom_fields(client: YouTrackClient, project_selector: str,
                          custom_fields: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if custom_fields is None:
        return None
    if not isinstance(custom_fields, list):
        raise CliError("custom fields must be a JSON array")
    if not custom_fields_need_schema(custom_fields):
        return custom_fields
    schema = client.project_fields(project_selector)
    resolved: list[dict[str, Any]] = []
    for item in custom_fields:
        if not isinstance(item, dict):
            raise CliError("each custom field must be a JSON object")
        selector_keys = [key for key in SELECTOR_KEYS if key in item]
        if not selector_keys:
            resolved.append(item)
            continue
        if len(selector_keys) != 1:
            raise CliError("each selector custom field must use exactly one selector key")
        selector_key = selector_keys[0]
        field_schema = find_schema_field(schema, item)
        payload = {key: value for key, value in item.items() if key not in SELECTOR_KEYS}
        payload.setdefault("name", field_name(field_schema))
        if selector_key == "$byName":
            payload["value"] = resolve_bundle_value(field_schema, item[selector_key])
        elif selector_key == "$byNames":
            names = item[selector_key]
            if not isinstance(names, list) or not all(isinstance(name, str) for name in names):
                raise CliError("$byNames must be a JSON array of strings")
            payload["value"] = [resolve_bundle_value(field_schema, name) for name in names]
        elif selector_key == "$user":
            if not isinstance(item[selector_key], str):
                raise CliError("$user must be a string")
            payload["value"] = client.resolve_user(item[selector_key])
        else:
            selectors = item[selector_key]
            if not isinstance(selectors, list) or not all(isinstance(name, str) for name in selectors):
                raise CliError("$users must be a JSON array of strings")
            payload["value"] = [client.resolve_user(name) for name in selectors]
        resolved.append(payload)
    return resolved


def field_name(field_schema: dict[str, Any]) -> str:
    field = field_schema.get("field")
    if not isinstance(field, dict) or not isinstance(field.get("name"), str):
        raise CliError("field schema entry is missing field.name")
    return field["name"]


def find_schema_field(schema: list[dict[str, Any]], item: dict[str, Any]) -> dict[str, Any]:
    target_name = item.get("name")
    target_id = item.get("id")
    matches: list[dict[str, Any]] = []
    for field_schema in schema:
        field = field_schema.get("field") if isinstance(field_schema, dict) else None
        if not isinstance(field, dict):
            continue
        if isinstance(target_id, str) and (field_schema.get("id") == target_id or field.get("id") == target_id):
            return field_schema
        matched = False
        if isinstance(target_name, str) and isinstance(field.get("name"), str):
            matched = field["name"].casefold() == target_name.casefold()
        if not matched and isinstance(target_name, str) and isinstance(field.get("localizedName"), str):
            matched = field["localizedName"].casefold() == target_name.casefold()
        if matched:
            matches.append(field_schema)
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise CliError(f"custom field {target_name!r} is ambiguous")
    hint = target_id or target_name
    raise CliError(f"custom field {hint!r} not found in project schema")


def resolve_bundle_value(field_schema: dict[str, Any], selector: str) -> dict[str, Any]:
    bundle = field_schema.get("bundle")
    values = bundle.get("values") if isinstance(bundle, dict) else None
    if not isinstance(values, list) or not values:
        raise CliError(f"custom field {field_name(field_schema)!r} does not expose selectable bundle values")
    exact: list[dict[str, Any]] = []
    normalized = selector.strip().casefold()
    for value in values:
        if not isinstance(value, dict):
            continue
        for key in ("id", "name", "localizedName", "presentation", "text"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip().casefold() == normalized:
                exact.append(value)
                break
    if len(exact) == 1:
        return {"id": str(exact[0]["id"])} if "id" in exact[0] else exact[0]
    if len(exact) > 1:
        raise CliError(f"bundle value {selector!r} is ambiguous for field {field_name(field_schema)!r}")
    preview = ", ".join(bundle_preview(value) for value in values[:8] if isinstance(value, dict))
    raise CliError(f"bundle value {selector!r} not found for field {field_name(field_schema)!r}: {preview}")


def bundle_preview(value: dict[str, Any]) -> str:
    for key in ("name", "localizedName", "presentation", "text", "id"):
        item = value.get(key)
        if isinstance(item, str) and item:
            return item
    return json.dumps(value, ensure_ascii=False)


def mutation_allowed(confirm_write: bool) -> bool:
    return env_bool("YOUTRACK_ALLOW_WRITE", False) and confirm_write


def require_write_gate(confirm_write: bool) -> None:
    if not env_bool("YOUTRACK_ALLOW_WRITE", False):
        raise CliError("writes are disabled: set YOUTRACK_ALLOW_WRITE=true")
    if not confirm_write:
        raise CliError("writes require explicit --confirm-write")


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="yt.py", description="generic YouTrack REST JSON CLI")
    command.add_argument("--url", default=os.environ.get("YOUTRACK_URL"), help="base URL, e.g. https://youtrack.example.net")
    command.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    command.add_argument("--confirm-write", action="store_true", help="required for create/update/comment mutations")
    subcommands = command.add_subparsers(dest="command", required=True)

    issues = subcommands.add_parser("issues", help="search issues")
    issues.add_argument("--query", required=True)
    issues.add_argument("--fields", default=ISSUE_FIELDS)
    issues.add_argument("--top", type=int, default=DEFAULT_TOP)
    issues.add_argument("--skip", type=int, default=0)

    issue = subcommands.add_parser("issue", help="get one issue")
    issue.add_argument("id")
    issue.add_argument("--fields", default=ISSUE_FIELDS)

    comments = subcommands.add_parser("comments", help="list issue comments")
    comments.add_argument("id")
    comments.add_argument("--fields", default=COMMENT_FIELDS)
    comments.add_argument("--top", type=int, default=DEFAULT_TOP)
    comments.add_argument("--skip", type=int, default=0)

    projects = subcommands.add_parser("projects", help="list or search projects")
    projects.add_argument("--query")
    projects.add_argument("--fields", default=PROJECT_FIELDS)
    projects.add_argument("--top", type=int, default=DEFAULT_TOP)
    projects.add_argument("--skip", type=int, default=0)

    users = subcommands.add_parser("users", help="list or search users")
    users.add_argument("--query", required=True)
    users.add_argument("--fields", default=USER_FIELDS)
    users.add_argument("--top", type=int, default=DEFAULT_TOP)
    users.add_argument("--skip", type=int, default=0)

    fields = subcommands.add_parser("fields", help="list issue custom field schema for a project")
    fields.add_argument("--project", default=os.environ.get("YOUTRACK_PROJECT"))
    fields.add_argument("--fields", default=FIELD_SCHEMA_FIELDS)
    fields.add_argument("--top", type=int, default=MAX_TOP)
    fields.add_argument("--skip", type=int, default=0)

    subcommands.add_parser("me", help="show current user")

    articles = subcommands.add_parser("articles", help="search articles")
    articles.add_argument("--query")
    articles.add_argument("--fields", default=ARTICLE_FIELDS)
    articles.add_argument("--top", type=int, default=DEFAULT_TOP)
    articles.add_argument("--skip", type=int, default=0)

    article = subcommands.add_parser("article", help="get one article")
    article.add_argument("id")
    article.add_argument("--fields", default=ARTICLE_GET_FIELDS)

    create = subcommands.add_parser("create", help="create an issue")
    create.add_argument("--project", default=os.environ.get("YOUTRACK_PROJECT"))
    create.add_argument("--summary", required=True)
    create.add_argument("--description", help="text, @file, or -")
    create.add_argument("--custom-fields", help="JSON array, @file, or -")

    update = subcommands.add_parser("update", help="update an issue")
    update.add_argument("id")
    update.add_argument("--project", default=os.environ.get("YOUTRACK_PROJECT"))
    update.add_argument("--summary")
    update.add_argument("--description", help="text, @file, or -")
    update.add_argument("--custom-fields", help="JSON array, @file, or -")

    comment = subcommands.add_parser("comment", help="add an issue comment")
    comment.add_argument("id")
    comment.add_argument("--text", required=True, help="text, @file, or -")

    article_create = subcommands.add_parser("article-create", help="create an article")
    article_create.add_argument("--project", default=os.environ.get("YOUTRACK_PROJECT"))
    article_create.add_argument("--summary", required=True)
    article_create.add_argument("--content", required=True, help="text, @file, or -")
    article_create.add_argument("--parent")

    article_update = subcommands.add_parser("article-update", help="update an article")
    article_update.add_argument("id")
    article_update.add_argument("--summary")
    article_update.add_argument("--content", help="text, @file, or -")
    return command


def require_project(value: str | None) -> str:
    if not value:
        raise CliError("missing project: pass --project or set YOUTRACK_PROJECT")
    return value


def run(args: argparse.Namespace) -> Any:
    if args.timeout <= 0:
        raise CliError("--timeout must be positive")
    if args.command in {"issues", "comments", "projects", "users", "fields", "articles"}:
        ensure_top(args.top)
        ensure_skip(args.skip)
    url = args.url or require_env("YOUTRACK_URL")
    token = require_env("YOUTRACK_TOKEN")
    client = YouTrackClient(url, token, timeout=args.timeout)

    if args.command == "issues":
        return client.get("issues", {
            "query": args.query,
            "fields": args.fields,
            "$top": args.top,
            "$skip": args.skip,
        })
    if args.command == "issue":
        return client.get(f"issues/{args.id}", {"fields": args.fields})
    if args.command == "comments":
        return client.get(f"issues/{args.id}/comments", {
            "fields": args.fields,
            "$top": args.top,
            "$skip": args.skip,
        })
    if args.command == "projects":
        return client.projects(query=args.query, fields=args.fields, top=args.top, skip=args.skip)
    if args.command == "users":
        return client.users(args.query, fields=args.fields, top=args.top, skip=args.skip)
    if args.command == "fields":
        project_id = client.resolve_project_id(require_project(args.project))
        return client.get(f"admin/projects/{project_id}/customFields", {
            "fields": args.fields,
            "$top": args.top,
            "$skip": args.skip,
        })
    if args.command == "me":
        return client.get("users/me", {"fields": USER_FIELDS})
    if args.command == "articles":
        return client.get("articles", {
            "query": args.query,
            "fields": args.fields,
            "$top": args.top,
            "$skip": args.skip,
        })
    if args.command == "article":
        return client.get(f"articles/{args.id}", {"fields": args.fields})
    if args.command == "create":
        require_write_gate(args.confirm_write)
        project = require_project(args.project)
        body: dict[str, Any] = {
            "project": {"id": client.resolve_project_id(project)},
            "summary": args.summary,
        }
        description = read_value(args.description)
        if description is not None:
            body["description"] = description
        custom_fields = resolve_custom_fields(
            client,
            project,
            read_json_arg(args.custom_fields, expected=list),
        )
        if custom_fields is not None:
            body["customFields"] = custom_fields
        return client.post("issues", body=body, params={"fields": "id,idReadable,summary"})
    if args.command == "update":
        require_write_gate(args.confirm_write)
        body: dict[str, Any] = {}
        if args.summary is not None:
            body["summary"] = args.summary
        description = read_value(args.description)
        if description is not None:
            body["description"] = description
        custom_fields = read_json_arg(args.custom_fields, expected=list)
        if custom_fields is not None:
            if custom_fields_need_schema(custom_fields):
                project = require_project(args.project)
                body["customFields"] = resolve_custom_fields(client, project, custom_fields)
            else:
                body["customFields"] = custom_fields
        if not body:
            raise CliError("update needs at least one change")
        return client.post(f"issues/{args.id}", body=body, params={"fields": "id,idReadable,summary"})
    if args.command == "comment":
        require_write_gate(args.confirm_write)
        return client.post(
            f"issues/{args.id}/comments",
            body={"text": read_value(args.text)},
            params={"fields": COMMENT_FIELDS},
        )
    if args.command == "article-create":
        require_write_gate(args.confirm_write)
        project = require_project(args.project)
        body = {
            "project": {"id": client.resolve_project_id(project)},
            "summary": args.summary,
            "content": read_value(args.content),
        }
        if args.parent:
            body["parentArticle"] = {"id": args.parent}
        return client.post("articles", body=body, params={"fields": "id,idReadable,summary"})
    require_write_gate(args.confirm_write)
    body = {}
    if args.summary is not None:
        body["summary"] = args.summary
    content = read_value(args.content)
    if content is not None:
        body["content"] = content
    if not body:
        raise CliError("article-update needs at least one change")
    return client.post(f"articles/{args.id}", body=body, params={"fields": "id,idReadable,summary"})


def main() -> None:
    try:
        emit(run(parser().parse_args()))
    except (CliError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error


if __name__ == "__main__":
    main()
