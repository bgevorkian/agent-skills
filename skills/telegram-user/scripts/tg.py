#!/usr/bin/env python
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import getpass
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.stdout.reconfigure(encoding="utf-8")

from telethon import TelegramClient, functions, types, utils
from telethon.errors import SessionPasswordNeededError
from telethon.tl.tlobject import TLObject

DEFAULT_LIMIT = 100
MAX_LIMIT = 1000
DEFAULT_TIMEOUT = 30.0
READ_PREFIXES = ("Get", "Search", "Check", "Resolve", "Fetch", "Load")
WRITE_TOKENS = (
    "Accept",
    "Add",
    "Archive",
    "Block",
    "Cancel",
    "Create",
    "Delete",
    "Discard",
    "Drop",
    "Edit",
    "Forward",
    "Import",
    "Install",
    "Invite",
    "Join",
    "Kick",
    "Leave",
    "Mark",
    "Pin",
    "Read",
    "Register",
    "Remove",
    "Report",
    "Reset",
    "Revoke",
    "Save",
    "Send",
    "Set",
    "Sign",
    "Start",
    "Stop",
    "Toggle",
    "Unarchive",
    "Unblock",
    "Uninstall",
    "Unpin",
    "Update",
)


class CLIError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    api_id: int | None
    api_hash: str | None
    session_file: Path
    allow_write: bool
    timeout: float


def parse_bool_env(value: str | None) -> bool:
    return (value or "").strip().lower() == "true"


def compute_default_session_file(
    env: dict[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    env = env or os.environ
    home = home or Path.home()
    platform = platform or os.name
    if platform == "nt":
        base = Path(env.get("APPDATA") or (home / "AppData" / "Roaming"))
    else:
        base = Path(env.get("XDG_DATA_HOME") or (home / ".local" / "share"))
    return base / "telegram-user" / "telethon.session"


def load_config(
    env: dict[str, str] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
    session_override: str | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Config:
    env = env or os.environ
    raw_api_id = (env.get("TELEGRAM_API_ID") or "").strip()
    api_id = int(raw_api_id) if raw_api_id else None
    api_hash = (env.get("TELEGRAM_API_HASH") or "").strip() or None
    session_raw = (session_override or env.get("TELEGRAM_SESSION_FILE") or "").strip()
    session_file = Path(os.path.expandvars(os.path.expanduser(session_raw))) if session_raw else compute_default_session_file(env, home, platform)
    return Config(
        api_id=api_id,
        api_hash=api_hash,
        session_file=session_file,
        allow_write=parse_bool_env(env.get("TELEGRAM_ALLOW_WRITE")),
        timeout=float(timeout),
    )


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return {"_type": "bytes", "hex": value.hex()}
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, TLObject):
        return to_jsonable(value.to_dict())
    if hasattr(value, "to_dict") and callable(value.to_dict):
        return to_jsonable(value.to_dict())
    if isinstance(value, dict):
        return {str(key): to_jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [to_jsonable(item) for item in value]
    return str(value)


def emit(payload: Any) -> None:
    print(json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2))


def fail(message: str, *, exit_code: int = 1) -> int:
    emit({"ok": False, "error": message})
    return exit_code


def bounded_limit(value: int) -> int:
    if value < 1:
        raise CLIError("limit must be >= 1")
    return min(value, MAX_LIMIT)


def parse_json_source(raw: str) -> Any:
    if raw == "-":
        text = sys.stdin.read()
    elif raw.startswith("@"):
        text = Path(raw[1:]).read_text(encoding="utf-8")
    else:
        text = raw
    return json.loads(text)


def resolve_type(name: str):
    if name.startswith("types."):
        name = name.split(".", 1)[1]
    obj = types
    for part in name.split("."):
        obj = getattr(obj, part)
    return obj


def inflate_tl(value: Any) -> Any:
    if isinstance(value, list):
        return [inflate_tl(item) for item in value]
    if isinstance(value, dict):
        if "_" in value:
            cls = resolve_type(str(value["_"]))
            kwargs = {key: inflate_tl(item) for key, item in value.items() if key != "_"}
            return cls(**kwargs)
        return {key: inflate_tl(item) for key, item in value.items()}
    return value


def raw_method_may_write(method_name: str) -> bool:
    leaf = method_name.split(".")[-1]
    if leaf.startswith("functions."):
        leaf = leaf.split(".")[-1]
    base = leaf[:-7] if leaf.endswith("Request") else leaf
    if any(token in base for token in WRITE_TOKENS):
        return True
    return not base.startswith(READ_PREFIXES)


def require_write_access(config: Config, confirmed: bool, *, reason: str) -> None:
    if config.allow_write and confirmed:
        return
    raise CLIError(
        f"{reason} requires TELEGRAM_ALLOW_WRITE=true and --confirm-write"
    )


def prompt_text(label: str, *, secret: bool = False) -> str:
    if secret:
        value = getpass.getpass(f"{label}: ")
    else:
        sys.stderr.write(f"{label}: ")
        sys.stderr.flush()
        value = sys.stdin.readline()
        if value == "":
            raise CLIError("interactive input cancelled")
        value = value.rstrip("\r\n")
    if not value.strip():
        raise CLIError(f"{label} is required")
    return value.strip()


def require_api_credentials(config: Config) -> tuple[int, str]:
    if config.api_id is None or not config.api_hash:
        raise CLIError(
            "missing TELEGRAM_API_ID or TELEGRAM_API_HASH; run login or set the environment"
        )
    return config.api_id, config.api_hash


def build_client(config: Config) -> TelegramClient:
    api_id, api_hash = require_api_credentials(config)
    config.session_file.parent.mkdir(parents=True, exist_ok=True)
    return TelegramClient(
        str(config.session_file),
        api_id,
        api_hash,
        receive_updates=False,
    )


async def ensure_authorized(client: TelegramClient) -> None:
    if not client.is_connected():
        await client.connect()
    if not await client.is_user_authorized():
        raise CLIError("session is not authorized; run the login command first")


async def resolve_entity(client: TelegramClient, ref: str):
    if ref == "me":
        return "me"
    try:
        return await client.get_entity(int(ref))
    except (TypeError, ValueError):
        return await client.get_entity(ref)


async def resolve_input_entity(client: TelegramClient, ref: str):
    entity = await resolve_entity(client, ref)
    if entity == "me":
        return types.InputPeerSelf()
    return await client.get_input_entity(entity)


async def entity_summary(client: TelegramClient, peer: Any) -> dict[str, Any]:
    entity = await client.get_entity(peer)
    if isinstance(entity, types.User):
        name = " ".join(part for part in [entity.first_name, entity.last_name] if part).strip()
        return {
            "id": entity.id,
            "type": "user",
            "name": name or entity.username or "",
            "username": entity.username,
            "phone": entity.phone,
            "bot": bool(entity.bot),
        }
    if isinstance(entity, types.Chat):
        return {"id": entity.id, "type": "chat", "name": entity.title}
    if isinstance(entity, types.Channel):
        return {
            "id": entity.id,
            "type": "channel",
            "name": entity.title,
            "username": entity.username,
            "megagroup": bool(entity.megagroup),
            "broadcast": bool(entity.broadcast),
        }
    return {"id": getattr(entity, "id", None), "type": type(entity).__name__, "name": str(entity)}


async def user_summary(client: TelegramClient, user: types.User | None = None) -> dict[str, Any]:
    user = user or await client.get_me()
    assert user is not None
    return await entity_summary(client, user)


async def dialog_filter_objects(client: TelegramClient) -> list[types.DialogFilter]:
    result = await client(functions.messages.GetDialogFiltersRequest())
    return [item for item in result.filters if isinstance(item, types.DialogFilter)]


def dialog_filter_title(dialog_filter: types.DialogFilter) -> str:
    title = getattr(dialog_filter, "title", None)
    return getattr(title, "text", title) or ""


def find_dialog_filter(filters: list[types.DialogFilter], ref: str) -> types.DialogFilter:
    if ref.isdigit():
        for item in filters:
            if getattr(item, "id", None) == int(ref):
                return item
    lowered = ref.lower()
    matches = [item for item in filters if lowered in dialog_filter_title(item).lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise CLIError(f"folder not found: {ref}")
    choices = ", ".join(f"id={item.id}:{dialog_filter_title(item)}" for item in matches)
    raise CLIError(f"folder reference is ambiguous: {choices}")


def peer_key(peer: Any) -> str:
    return json.dumps(to_jsonable(peer), sort_keys=True, ensure_ascii=False)


def message_summary(message: Any) -> dict[str, Any]:
    peer_id = getattr(message, "peer_id", None)
    sender_id = getattr(message, "sender_id", None)
    return {
        "id": message.id,
        "date": message.date.isoformat() if getattr(message, "date", None) else None,
        "text": message.message or "",
        "out": bool(getattr(message, "out", False)),
        "chat_id": utils.get_peer_id(peer_id) if peer_id is not None else None,
        "sender_id": sender_id,
        "reply_to_msg_id": getattr(getattr(message, "reply_to", None), "reply_to_msg_id", None),
    }


async def run_with_timeout(config: Config, coro):
    return await asyncio.wait_for(coro, timeout=config.timeout)


async def cmd_login(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    api_id = config.api_id
    api_hash = config.api_hash
    if api_id is None:
        api_id = int(prompt_text("TELEGRAM_API_ID"))
    if not api_hash:
        api_hash = prompt_text("TELEGRAM_API_HASH", secret=True)
    phone = args.phone or prompt_text("phone")

    config.session_file.parent.mkdir(parents=True, exist_ok=True)
    client = TelegramClient(str(config.session_file), api_id, api_hash, receive_updates=False)
    try:
        await client.connect()
        if not await client.is_user_authorized():
            sent = await client.send_code_request(phone)
            try:
                code = prompt_text("login code", secret=True)
                await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
            except SessionPasswordNeededError:
                password = prompt_text("2FA password", secret=True)
                await client.sign_in(password=password)
        me = await client.get_me()
        return {"ok": True, "authorized": True, "user": await user_summary(client, me)}
    finally:
        await client.disconnect()


async def cmd_status(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    configured = config.api_id is not None and bool(config.api_hash)
    session_present = config.session_file.exists()
    result: dict[str, Any] = {
        "ok": True,
        "configured": configured,
        "session_file_present": session_present,
        "allow_write": config.allow_write,
    }
    if not configured:
        result["authorized"] = None
        return result

    client = build_client(config)
    try:
        await client.connect()
        authorized = await client.is_user_authorized()
        result["authorized"] = authorized
        if authorized:
            result["user"] = await user_summary(client)
        return result
    finally:
        await client.disconnect()


async def cmd_me(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    client = build_client(config)
    try:
        await ensure_authorized(client)
        return {"ok": True, "user": await user_summary(client)}
    finally:
        await client.disconnect()


async def cmd_dialogs(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    client = build_client(config)
    try:
        await ensure_authorized(client)
        rows = []
        async for dialog in client.iter_dialogs(limit=bounded_limit(args.limit)):
            rows.append(
                {
                    "id": dialog.id,
                    "name": dialog.name,
                    "type": "user" if dialog.is_user else "group" if dialog.is_group else "channel",
                    "unread_count": dialog.unread_count,
                    "unread_mentions": dialog.unread_mentions_count,
                    "archived": bool(dialog.archived),
                    "pinned": bool(dialog.pinned),
                }
            )
        return {"ok": True, "rows": rows, "row_count": len(rows)}
    finally:
        await client.disconnect()


async def cmd_messages(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    client = build_client(config)
    try:
        await ensure_authorized(client)
        entity = await resolve_entity(client, args.chat)
        rows = [
            message_summary(item)
            async for item in client.iter_messages(
                entity,
                limit=bounded_limit(args.limit),
                offset_id=args.offset_id,
            )
        ]
        return {"ok": True, "rows": rows, "row_count": len(rows)}
    finally:
        await client.disconnect()


async def cmd_search(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    client = build_client(config)
    try:
        await ensure_authorized(client)
        entity = await resolve_entity(client, args.chat) if args.chat else None
        rows = [
            message_summary(item)
            async for item in client.iter_messages(
                entity,
                search=args.query,
                limit=bounded_limit(args.limit),
                offset_id=args.offset_id,
            )
        ]
        return {"ok": True, "rows": rows, "row_count": len(rows)}
    finally:
        await client.disconnect()


async def cmd_send(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="send")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        entity = await resolve_entity(client, args.chat)
        message = await client.send_message(entity, args.text)
        return {"ok": True, "message": message_summary(message)}
    finally:
        await client.disconnect()


async def cmd_edit(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="edit")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        entity = await resolve_entity(client, args.chat)
        message = await client.edit_message(entity, args.message_id, args.text)
        return {"ok": True, "message": message_summary(message)}
    finally:
        await client.disconnect()


async def cmd_delete(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="delete")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        entity = await resolve_entity(client, args.chat)
        await client.delete_messages(entity, list(args.message_ids), revoke=not args.local_only)
        return {"ok": True, "deleted_ids": list(args.message_ids), "revoke": not args.local_only}
    finally:
        await client.disconnect()


async def cmd_saved_messages(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    args.chat = "me"
    return await cmd_messages(args, config)


async def cmd_saved_send(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="saved send")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        message = await client.send_message("me", args.text)
        return {"ok": True, "message": message_summary(message)}
    finally:
        await client.disconnect()


async def folder_summary(client: TelegramClient, dialog_filter: types.DialogFilter) -> dict[str, Any]:
    async def peers(items: list[Any]) -> list[dict[str, Any]]:
        return [await entity_summary(client, item) for item in items]

    include_peers = list(getattr(dialog_filter, "include_peers", []) or [])
    pinned_peers = list(getattr(dialog_filter, "pinned_peers", []) or [])
    exclude_peers = list(getattr(dialog_filter, "exclude_peers", []) or [])
    return {
        "id": dialog_filter.id,
        "title": dialog_filter_title(dialog_filter),
        "include_peers": await peers(include_peers),
        "pinned_peers": await peers(pinned_peers),
        "exclude_peers": await peers(exclude_peers),
    }


async def cmd_folders_list(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    client = build_client(config)
    try:
        await ensure_authorized(client)
        rows = []
        for item in await dialog_filter_objects(client):
            rows.append(
                {
                    "id": item.id,
                    "title": dialog_filter_title(item),
                    "include_count": len(list(getattr(item, "include_peers", []) or [])),
                    "pinned_count": len(list(getattr(item, "pinned_peers", []) or [])),
                    "exclude_count": len(list(getattr(item, "exclude_peers", []) or [])),
                }
            )
        return {"ok": True, "rows": rows, "row_count": len(rows)}
    finally:
        await client.disconnect()


async def cmd_folders_get(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    client = build_client(config)
    try:
        await ensure_authorized(client)
        dialog_filter = find_dialog_filter(await dialog_filter_objects(client), args.ref)
        return {"ok": True, "folder": await folder_summary(client, dialog_filter)}
    finally:
        await client.disconnect()


async def mutate_folder_peers(
    client: TelegramClient,
    dialog_filter: types.DialogFilter,
    peer_refs: list[str],
    *,
    remove: bool,
) -> dict[str, Any]:
    peers = [await resolve_input_entity(client, ref) for ref in peer_refs]
    keys = {peer_key(peer) for peer in peers}

    include = list(getattr(dialog_filter, "include_peers", []) or [])
    pinned = list(getattr(dialog_filter, "pinned_peers", []) or [])
    before_include = len(include)
    before_pinned = len(pinned)

    if remove:
        include = [item for item in include if peer_key(item) not in keys]
        pinned = [item for item in pinned if peer_key(item) not in keys]
    else:
        seen = {peer_key(item) for item in include}
        for item in peers:
            key = peer_key(item)
            if key not in seen:
                include.append(item)
                seen.add(key)

    dialog_filter.include_peers = include
    dialog_filter.pinned_peers = pinned
    await client(functions.messages.UpdateDialogFilterRequest(id=dialog_filter.id, filter=dialog_filter))
    return {
        "folder_id": dialog_filter.id,
        "folder_title": dialog_filter_title(dialog_filter),
        "include_count": len(include),
        "pinned_count": len(pinned),
        "added": 0 if remove else len(include) - before_include,
        "removed": (before_include - len(include)) + (before_pinned - len(pinned)) if remove else 0,
    }


async def cmd_folders_add_peers(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="folder update")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        dialog_filter = find_dialog_filter(await dialog_filter_objects(client), args.ref)
        result = await mutate_folder_peers(client, dialog_filter, args.peers, remove=False)
        return {"ok": True, **result}
    finally:
        await client.disconnect()


async def cmd_folders_remove_peers(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="folder update")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        dialog_filter = find_dialog_filter(await dialog_filter_objects(client), args.ref)
        result = await mutate_folder_peers(client, dialog_filter, args.peers, remove=True)
        return {"ok": True, **result}
    finally:
        await client.disconnect()


async def cmd_folders_set_title(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="folder update")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        dialog_filter = find_dialog_filter(await dialog_filter_objects(client), args.ref)
        dialog_filter.title = args.title
        await client(functions.messages.UpdateDialogFilterRequest(id=dialog_filter.id, filter=dialog_filter))
        return {"ok": True, "folder_id": dialog_filter.id, "title": args.title}
    finally:
        await client.disconnect()


async def cmd_contacts_list(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    client = build_client(config)
    try:
        await ensure_authorized(client)
        query = (args.search or "").lower()
        contacts = await client.get_contacts()
        rows = []
        for item in contacts:
            row = await entity_summary(client, item)
            haystack = " ".join(str(row.get(key) or "") for key in ("name", "username", "phone")).lower()
            if query and query not in haystack:
                continue
            rows.append(row)
            if len(rows) >= bounded_limit(args.limit):
                break
        return {"ok": True, "rows": rows, "row_count": len(rows)}
    finally:
        await client.disconnect()


async def cmd_contacts_add(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="contact mutation")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        request = functions.contacts.ImportContactsRequest(
            contacts=[
                types.InputPhoneContact(
                    client_id=int(time.time_ns() & ((1 << 63) - 1)),
                    phone=args.phone,
                    first_name=args.first_name,
                    last_name=args.last_name or "",
                )
            ]
        )
        result = await client(request)
        users = [await entity_summary(client, user) for user in result.users]
        return {"ok": True, "rows": users, "row_count": len(users)}
    finally:
        await client.disconnect()


async def cmd_contacts_delete(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    require_write_access(config, args.confirm_write, reason="contact mutation")
    client = build_client(config)
    try:
        await ensure_authorized(client)
        input_users = []
        for ref in args.peers:
            entity = await resolve_entity(client, ref)
            input_users.append(utils.get_input_user(entity))
        result = await client(functions.contacts.DeleteContactsRequest(id=input_users))
        return {"ok": True, "deleted": len(args.peers), "result": to_jsonable(result)}
    finally:
        await client.disconnect()


def resolve_function_class(name: str):
    parts = name.split(".")
    if parts[0] == "functions":
        parts = parts[1:]
    obj: Any = functions
    for part in parts:
        obj = getattr(obj, part)
    return obj


async def cmd_raw(args: argparse.Namespace, config: Config) -> dict[str, Any]:
    if raw_method_may_write(args.method):
        require_write_access(config, args.confirm_write, reason="raw method")
    payload = inflate_tl(parse_json_source(args.args))
    if not isinstance(payload, dict):
        raise CLIError("raw arguments must decode to a JSON object")
    request_cls = resolve_function_class(args.method)
    client = build_client(config)
    try:
        await ensure_authorized(client)
        result = await client(request_cls(**payload))
        return {"ok": True, "result": to_jsonable(result)}
    finally:
        await client.disconnect()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tg", description="Telegram user-account JSON CLI")
    parser.add_argument("--session-file", help="override TELEGRAM_SESSION_FILE")
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT, help="overall command timeout in seconds")
    parser.add_argument("--confirm-write", action="store_true", help="required with TELEGRAM_ALLOW_WRITE=true for mutating commands")
    sub = parser.add_subparsers(dest="command", required=True)

    login = sub.add_parser("login", help="interactive setup and authorization")
    login.add_argument("--phone", default=None, help="phone number in international format")
    login.set_defaults(fn=cmd_login)

    status = sub.add_parser("status", help="check configuration and authorization status")
    status.set_defaults(fn=cmd_status)

    me = sub.add_parser("me", help="show the current account")
    me.set_defaults(fn=cmd_me)

    dialogs = sub.add_parser("dialogs", help="list dialogs")
    dialogs.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    dialogs.set_defaults(fn=cmd_dialogs)

    messages = sub.add_parser("messages", help="list messages from a chat")
    messages.add_argument("chat")
    messages.add_argument("--limit", type=int, default=20)
    messages.add_argument("--offset-id", type=int, default=0)
    messages.set_defaults(fn=cmd_messages)

    search = sub.add_parser("search", help="search messages")
    search.add_argument("query")
    search.add_argument("--chat", default=None)
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset-id", type=int, default=0)
    search.set_defaults(fn=cmd_search)

    send = sub.add_parser("send", help="send a message")
    send.add_argument("chat")
    send.add_argument("text")
    send.set_defaults(fn=cmd_send)

    edit = sub.add_parser("edit", help="edit a message")
    edit.add_argument("chat")
    edit.add_argument("message_id", type=int)
    edit.add_argument("text")
    edit.set_defaults(fn=cmd_edit)

    delete = sub.add_parser("delete", help="delete messages")
    delete.add_argument("chat")
    delete.add_argument("message_ids", nargs="+", type=int)
    delete.add_argument("--local-only", action="store_true", help="do not revoke for other participants")
    delete.set_defaults(fn=cmd_delete)

    saved = sub.add_parser("saved", help="work with Saved Messages")
    saved_sub = saved.add_subparsers(dest="saved_command", required=True)

    saved_messages = saved_sub.add_parser("messages", help="list Saved Messages")
    saved_messages.add_argument("--limit", type=int, default=20)
    saved_messages.add_argument("--offset-id", type=int, default=0)
    saved_messages.set_defaults(fn=cmd_saved_messages)

    saved_send = saved_sub.add_parser("send", help="send to Saved Messages")
    saved_send.add_argument("text")
    saved_send.set_defaults(fn=cmd_saved_send)

    folders = sub.add_parser("folders", help="list and update dialog filters")
    folders_sub = folders.add_subparsers(dest="folders_command", required=True)

    folders_list = folders_sub.add_parser("list", help="list folders")
    folders_list.set_defaults(fn=cmd_folders_list)

    folders_get = folders_sub.add_parser("get", help="show one folder")
    folders_get.add_argument("ref")
    folders_get.set_defaults(fn=cmd_folders_get)

    folders_add = folders_sub.add_parser("add-peers", help="add peers to a folder")
    folders_add.add_argument("ref")
    folders_add.add_argument("peers", nargs="+")
    folders_add.set_defaults(fn=cmd_folders_add_peers)

    folders_remove = folders_sub.add_parser("remove-peers", help="remove peers from a folder")
    folders_remove.add_argument("ref")
    folders_remove.add_argument("peers", nargs="+")
    folders_remove.set_defaults(fn=cmd_folders_remove_peers)

    folders_title = folders_sub.add_parser("set-title", help="rename a folder")
    folders_title.add_argument("ref")
    folders_title.add_argument("title")
    folders_title.set_defaults(fn=cmd_folders_set_title)

    contacts = sub.add_parser("contacts", help="list and mutate contacts")
    contacts_sub = contacts.add_subparsers(dest="contacts_command", required=True)

    contacts_list = contacts_sub.add_parser("list", help="list contacts")
    contacts_list.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    contacts_list.add_argument("--search", default=None)
    contacts_list.set_defaults(fn=cmd_contacts_list)

    contacts_add = contacts_sub.add_parser("add", help="add a contact by phone")
    contacts_add.add_argument("--phone", required=True)
    contacts_add.add_argument("--first-name", required=True)
    contacts_add.add_argument("--last-name", default="")
    contacts_add.set_defaults(fn=cmd_contacts_add)

    contacts_delete = contacts_sub.add_parser("delete", help="delete contacts")
    contacts_delete.add_argument("peers", nargs="+")
    contacts_delete.set_defaults(fn=cmd_contacts_delete)

    raw = sub.add_parser("raw", help="call a Telethon functions.* request")
    raw.add_argument("method")
    raw.add_argument("args", nargs="?", default="{}", help="JSON object, @file.json, or - for stdin")
    raw.set_defaults(fn=cmd_raw)

    return parser


async def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    config = load_config(timeout=args.timeout, session_override=args.session_file)
    return await run_with_timeout(config, args.fn(args, config))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        emit(asyncio.run(dispatch(args)))
        return 0
    except KeyboardInterrupt:
        return fail("cancelled", exit_code=130)
    except CLIError as exc:
        return fail(str(exc))
    except Exception as exc:  # noqa: BLE001
        return fail(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
