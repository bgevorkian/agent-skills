from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from uuid import UUID

import tidalapi

RESOURCE_KINDS = ("track", "album", "artist", "playlist")
SEARCH_MODELS = {
    "track": tidalapi.Track,
    "album": tidalapi.Album,
    "artist": tidalapi.Artist,
    "playlist": tidalapi.Playlist,
}


def user_data_dir(
    env: dict[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    env = env or os.environ
    home = home or Path.home()
    platform = platform or sys.platform
    xdg = env.get("XDG_DATA_HOME")
    if xdg:
        return Path(xdg) / "agent-skills" / "tidal"
    if platform.startswith("win"):
        root = env.get("APPDATA") or env.get("LOCALAPPDATA")
        if root:
            return Path(root) / "agent-skills" / "tidal"
        return home / "AppData" / "Roaming" / "agent-skills" / "tidal"
    if platform == "darwin":
        return home / "Library" / "Application Support" / "agent-skills" / "tidal"
    return home / ".local" / "share" / "agent-skills" / "tidal"


def session_file_path(
    env: dict[str, str] | None = None,
    home: Path | None = None,
    platform: str | None = None,
) -> Path:
    env = env or os.environ
    if env.get("TIDAL_SESSION_FILE"):
        return Path(env["TIDAL_SESSION_FILE"]).expanduser()
    return user_data_dir(env=env, home=home, platform=platform) / "session.json"


def env_write_enabled(env: dict[str, str] | None = None) -> bool:
    env = env or os.environ
    return env.get("TIDAL_ALLOW_WRITE", "").strip().lower() == "true"


def require_write_enabled(confirm_write: bool, env: dict[str, str] | None = None) -> None:
    if not env_write_enabled(env):
        raise ValueError("writes are disabled; set TIDAL_ALLOW_WRITE=true")
    if not confirm_write:
        raise ValueError("writes require explicit --confirm-write")


def clamp_limit(limit: int, maximum: int) -> int:
    if limit < 1:
        raise ValueError("--limit must be at least 1")
    if limit > maximum:
        raise ValueError(f"--limit must be <= {maximum}")
    return limit


def jsonable(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
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


def value_or_none(obj: Any, *names: str) -> Any:
    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if callable(value):
                continue
            if value is not None:
                return value
    return None


def artist_name(obj: Any) -> str | None:
    artist = value_or_none(obj, "artist")
    if artist is not None:
        return value_or_none(artist, "name")
    artists = value_or_none(obj, "artists")
    if artists:
        first = artists[0]
        return value_or_none(first, "name")
    return None


def canonical_url(kind: str, resource_id: str) -> str:
    return f"https://tidal.com/browse/{kind}/{resource_id}"


def track_to_json(track: Any) -> dict[str, Any]:
    track_id = value_or_none(track, "id")
    return {
        "kind": "track",
        "id": jsonable(track_id),
        "title": value_or_none(track, "name", "title"),
        "artist": artist_name(track),
        "album": value_or_none(value_or_none(track, "album"), "name", "title"),
        "duration": value_or_none(track, "duration"),
        "version": value_or_none(track, "version"),
        "explicit": value_or_none(track, "explicit"),
        "popularity": value_or_none(track, "popularity"),
        "isrc": value_or_none(track, "isrc"),
        "url": value_or_none(track, "share_url", "listen_url") or (canonical_url("track", str(track_id)) if track_id is not None else None),
    }


def album_to_json(album: Any) -> dict[str, Any]:
    album_id = value_or_none(album, "id")
    return {
        "kind": "album",
        "id": jsonable(album_id),
        "title": value_or_none(album, "name", "title"),
        "artist": artist_name(album),
        "num_tracks": value_or_none(album, "num_tracks", "number_of_tracks"),
        "num_volumes": value_or_none(album, "num_volumes", "number_of_volumes"),
        "release_date": jsonable(value_or_none(album, "release_date", "stream_start_date")),
        "explicit": value_or_none(album, "explicit"),
        "url": value_or_none(album, "share_url", "listen_url") or (canonical_url("album", str(album_id)) if album_id is not None else None),
    }


def artist_to_json(artist: Any) -> dict[str, Any]:
    artist_id = value_or_none(artist, "id")
    return {
        "kind": "artist",
        "id": jsonable(artist_id),
        "name": value_or_none(artist, "name"),
        "popularity": value_or_none(artist, "popularity"),
        "url": value_or_none(artist, "share_url", "listen_url") or (canonical_url("artist", str(artist_id)) if artist_id is not None else None),
    }


def playlist_to_json(playlist: Any) -> dict[str, Any]:
    playlist_id = value_or_none(playlist, "id")
    return {
        "kind": "playlist",
        "id": jsonable(playlist_id),
        "title": value_or_none(playlist, "name", "title"),
        "description": value_or_none(playlist, "description"),
        "num_tracks": value_or_none(playlist, "num_tracks"),
        "public": value_or_none(playlist, "public"),
        "creator": value_or_none(value_or_none(playlist, "creator"), "name", "id"),
        "created": jsonable(value_or_none(playlist, "created")),
        "last_updated": jsonable(value_or_none(playlist, "last_updated")),
        "url": value_or_none(playlist, "share_url", "listen_url") or (canonical_url("playlist", str(playlist_id)) if playlist_id is not None else None),
    }


def item_to_json(kind: str, item: Any) -> dict[str, Any]:
    if kind == "track":
        return track_to_json(item)
    if kind == "album":
        return album_to_json(item)
    if kind == "artist":
        return artist_to_json(item)
    if kind == "playlist":
        return playlist_to_json(item)
    raise ValueError(f"unsupported kind: {kind}")


def me_to_json(user: Any) -> dict[str, Any]:
    return {
        "id": jsonable(value_or_none(user, "id")),
        "username": value_or_none(user, "username"),
        "email": value_or_none(user, "email"),
        "first_name": value_or_none(user, "first_name"),
        "last_name": value_or_none(user, "last_name"),
    }


def expand_csv(values: list[str] | None) -> list[str]:
    result: list[str] = []
    for value in values or []:
        for part in value.split(","):
            item = part.strip()
            if item:
                result.append(item)
    return result


def parse_indices(values: list[str] | None) -> list[int]:
    result: list[int] = []
    for value in expand_csv(values):
        index = int(value)
        if index < 0:
            raise ValueError("indices must be non-negative")
        result.append(index)
    return sorted(dict.fromkeys(result))


def parse_reference(value: str, expected_kind: str | None = None) -> dict[str, str]:
    raw = value.strip()
    if not raw:
        raise ValueError("empty id/url")

    parsed = urlparse(raw)
    if parsed.scheme and parsed.netloc:
        host = parsed.netloc.lower()
        if "tidal.com" not in host:
            raise ValueError(f"unsupported URL host: {parsed.netloc}")
        parts = [part for part in parsed.path.split("/") if part]
        while parts and parts[0] == "browse":
            parts.pop(0)
        if len(parts) >= 3 and parts[1] in RESOURCE_KINDS:
            parts = parts[1:]
        for index, part in enumerate(parts[:-1]):
            if part in RESOURCE_KINDS:
                kind = part
                resource_id = parts[index + 1]
                break
        else:
            raise ValueError(f"could not resolve TIDAL resource from URL: {value}")
        if expected_kind and kind != expected_kind:
            raise ValueError(f"expected {expected_kind} but got {kind}")
        return {"input": value, "kind": kind, "id": resource_id, "url": canonical_url(kind, resource_id)}

    lowered = raw.lower()
    for separator in (":", "/"):
        prefix, marker, rest = lowered.partition(separator)
        if marker and prefix in RESOURCE_KINDS:
            resource_id = raw[len(prefix) + 1 :].strip()
            if not resource_id:
                raise ValueError(f"missing id after {prefix}{separator}")
            if expected_kind and prefix != expected_kind:
                raise ValueError(f"expected {expected_kind} but got {prefix}")
            return {"input": value, "kind": prefix, "id": resource_id, "url": canonical_url(prefix, resource_id)}

    if expected_kind:
        return {"input": value, "kind": expected_kind, "id": raw, "url": canonical_url(expected_kind, raw)}
    if raw.isdigit():
        raise ValueError("numeric ids are ambiguous; pass --kind or use track:/album:/artist:")
    if any(char.isalpha() for char in raw) or "-" in raw:
        return {"input": value, "kind": "playlist", "id": raw, "url": canonical_url("playlist", raw)}
    raise ValueError("could not infer resource kind; pass --kind")


def load_session(require_login: bool = True) -> tuple[tidalapi.Session, Path]:
    path = session_file_path()
    if not path.exists():
        raise ValueError(f"missing session file; run auth-login first ({path})")
    session = tidalapi.Session()
    session.load_session_from_file(path)
    if require_login and not session.check_login():
        raise ValueError(f"stored session is expired; run auth-login again ({path})")
    return session, path


def session_status() -> dict[str, Any]:
    path = session_file_path()
    status: dict[str, Any] = {
        "session_file": str(path),
        "exists": path.exists(),
        "logged_in": False,
    }
    if not path.exists():
        return status
    session = tidalapi.Session()
    try:
        session.load_session_from_file(path)
        status["logged_in"] = bool(session.check_login())
        if status["logged_in"] and session.user is not None:
            status["user"] = me_to_json(session.user)
    except Exception as error:
        status["error"] = f"{type(error).__name__}: {error}"
    return status


def save_session_interactive() -> dict[str, Any]:
    current = session_status()
    if current.get("logged_in"):
        current["message"] = "session already valid"
        return current
    path = session_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    session = tidalapi.Session()
    session.login_oauth_simple(fn_print=lambda message: print(message, file=sys.stderr))
    if not session.check_login():
        raise ValueError("TIDAL login did not complete")
    session.save_session_to_file(path)
    return {
        "logged_in": True,
        "session_file": str(path),
        "user": me_to_json(session.user),
        "message": "session saved",
    }


def fetch_resource(session: tidalapi.Session, kind: str, resource_id: str) -> Any:
    if kind == "track":
        return session.track(resource_id)
    if kind == "album":
        return session.album(resource_id)
    if kind == "artist":
        return session.artist(resource_id)
    if kind == "playlist":
        return session.playlist(resource_id)
    raise ValueError(f"unsupported kind: {kind}")


def resolve_many(values: list[str], kind: str | None, fetch: bool) -> dict[str, Any]:
    refs = [parse_reference(value, kind) for value in values]
    payload: dict[str, Any] = {"items": refs, "count": len(refs)}
    if fetch:
        session, _ = load_session(require_login=True)
        payload["items"] = [
            {**ref, "resource": item_to_json(ref["kind"], fetch_resource(session, ref["kind"], ref["id"]))}
            for ref in refs
        ]
    return payload


def list_playlists(args: argparse.Namespace) -> dict[str, Any]:
    session, _ = load_session(require_login=True)
    playlists = session.user.playlists()
    total = len(playlists)
    items = playlists[args.offset : args.offset + args.limit]
    return {
        "offset": args.offset,
        "limit": args.limit,
        "total_count": total,
        "items": [playlist_to_json(item) for item in items],
    }


def playlist_tracks(args: argparse.Namespace) -> dict[str, Any]:
    session, _ = load_session(require_login=True)
    ref = parse_reference(args.playlist, "playlist")
    playlist = session.playlist(ref["id"])
    tracks = playlist.tracks(limit=args.limit, offset=args.offset)
    return {
        "playlist": playlist_to_json(playlist),
        "offset": args.offset,
        "limit": args.limit,
        "items": [track_to_json(track) for track in tracks],
        "row_count": len(tracks),
    }


def search_items(args: argparse.Namespace) -> dict[str, Any]:
    session, _ = load_session(require_login=True)
    limit = clamp_limit(args.limit, 300)
    models = None if args.type == "all" else [SEARCH_MODELS[args.type]]
    results = session.search(args.query, models=models, limit=limit, offset=args.offset)
    requested = RESOURCE_KINDS if args.type == "all" else (args.type,)
    payload: dict[str, Any] = {
        "query": args.query,
        "offset": args.offset,
        "limit": limit,
        "results": {kind: [item_to_json(kind, item) for item in results.get(f"{kind}s", [])] for kind in requested},
    }
    top_hit = results.get("top_hit")
    if top_hit is not None:
        hit_kind = getattr(top_hit, "type", None)
        if hit_kind in RESOURCE_KINDS:
            payload["top_hit"] = item_to_json(hit_kind, top_hit)
    return payload


def favorites_api(session: tidalapi.Session) -> Any:
    favorites = getattr(session.user, "favorites", None)
    if favorites is None:
        raise ValueError("favorites are not supported by this tidalapi session")
    return favorites


def list_favorites(args: argparse.Namespace) -> dict[str, Any]:
    session, _ = load_session(require_login=True)
    favorites = favorites_api(session)
    kind = args.type
    items = getattr(favorites, f"{kind}s")(limit=args.limit, offset=args.offset)
    total = getattr(favorites, f"get_{kind}s_count")()
    return {
        "type": kind,
        "offset": args.offset,
        "limit": args.limit,
        "total_count": total,
        "items": [item_to_json(kind, item) for item in items],
    }


def create_playlist(args: argparse.Namespace) -> dict[str, Any]:
    require_write_enabled(args.confirm_write)
    session, _ = load_session(require_login=True)
    playlist = session.user.create_playlist(args.title, args.description or "")
    return {"playlist": playlist_to_json(playlist), "created": True}


def rename_playlist(args: argparse.Namespace) -> dict[str, Any]:
    require_write_enabled(args.confirm_write)
    if args.title is None and args.description is None:
        raise ValueError("pass --title and/or --description")
    session, _ = load_session(require_login=True)
    ref = parse_reference(args.playlist, "playlist")
    playlist = session.playlist(ref["id"])
    ok = playlist.edit(title=args.title, description=args.description)
    return {"ok": bool(ok), "playlist": playlist_to_json(playlist)}


def delete_playlist(args: argparse.Namespace) -> dict[str, Any]:
    require_write_enabled(args.confirm_write)
    session, _ = load_session(require_login=True)
    ref = parse_reference(args.playlist, "playlist")
    playlist = session.playlist(ref["id"])
    snapshot = playlist_to_json(playlist)
    ok = playlist.delete()
    return {"ok": bool(ok), "deleted": snapshot}


def resolve_track_ids(values: list[str]) -> list[str]:
    refs = [parse_reference(value, "track") for value in values]
    return [ref["id"] for ref in refs]


def add_tracks(args: argparse.Namespace) -> dict[str, Any]:
    require_write_enabled(args.confirm_write)
    track_values = expand_csv(args.track)
    if not track_values:
        raise ValueError("pass at least one --track")
    session, _ = load_session(require_login=True)
    playlist_ref = parse_reference(args.playlist, "playlist")
    playlist = session.playlist(playlist_ref["id"])
    added = playlist.add(resolve_track_ids(track_values), allow_duplicates=args.allow_duplicates, position=args.position)
    return {
        "playlist": playlist_to_json(playlist),
        "requested_track_ids": resolve_track_ids(track_values),
        "added_track_ids": jsonable(added),
        "added_count": len(added),
    }


def playlist_track_ids(playlist: Any) -> list[str]:
    return [str(value_or_none(track, "id")) for track in playlist.tracks_paginated()]


def remove_tracks(args: argparse.Namespace) -> dict[str, Any]:
    require_write_enabled(args.confirm_write)
    session, _ = load_session(require_login=True)
    playlist_ref = parse_reference(args.playlist, "playlist")
    playlist = session.playlist(playlist_ref["id"])
    indices = parse_indices(args.index)
    track_values = expand_csv(args.track)

    if indices and track_values:
        raise ValueError("use either --index or --track, not both")
    if not indices and not track_values:
        raise ValueError("pass --index or --track")

    removed = False
    details: dict[str, Any] = {}
    if indices:
        removed = playlist.remove_by_indices(indices)
        details["indices"] = indices
    else:
        track_ids = resolve_track_ids(track_values)
        details["track_ids"] = track_ids
        if args.all_matches:
            current = playlist_track_ids(playlist)
            matches = [index for index, track_id in enumerate(current) if track_id in set(track_ids)]
            if not matches:
                removed = False
                details["indices"] = []
            else:
                removed = playlist.remove_by_indices(matches)
                details["indices"] = matches
        else:
            per_track = {track_id: bool(playlist.remove_by_id(track_id)) for track_id in track_ids}
            removed = all(per_track.values())
            details["per_track"] = per_track
    return {"ok": bool(removed), **details, "playlist": playlist_to_json(playlist)}


def reorder_tracks(args: argparse.Namespace) -> dict[str, Any]:
    require_write_enabled(args.confirm_write)
    session, _ = load_session(require_login=True)
    playlist_ref = parse_reference(args.playlist, "playlist")
    playlist = session.playlist(playlist_ref["id"])
    indices = parse_indices(args.index)
    track_values = expand_csv(args.track)
    if indices and track_values:
        raise ValueError("use either --index or --track, not both")
    if not indices and not track_values:
        raise ValueError("pass --index or --track")

    if indices:
        ok = playlist.move_by_indices(indices, args.position) if len(indices) > 1 else playlist.move_by_index(indices[0], args.position)
        details: dict[str, Any] = {"indices": indices}
    else:
        track_ids = resolve_track_ids(track_values)
        if len(track_ids) != 1:
            raise ValueError("track-based reorder accepts exactly one track id/url")
        ok = playlist.move_by_id(track_ids[0], args.position)
        details = {"track_id": track_ids[0]}
    return {"ok": bool(ok), "position": args.position, **details, "playlist": playlist_to_json(playlist)}


def favorite_mutation(args: argparse.Namespace, remove: bool) -> dict[str, Any]:
    require_write_enabled(args.confirm_write)
    values = expand_csv(args.item)
    if not values:
        raise ValueError("pass at least one --item")
    session, _ = load_session(require_login=True)
    favorites = favorites_api(session)
    refs = [parse_reference(value, args.type) for value in values]
    ids = [ref["id"] for ref in refs]
    if remove:
        if len(ids) != 1:
            raise ValueError("favorite-remove accepts exactly one item")
        ok = getattr(favorites, f"remove_{args.type}")(ids[0])
    else:
        ok = getattr(favorites, f"add_{args.type}")(ids)
    return {"ok": bool(ok), "type": args.type, "ids": ids, "action": "remove" if remove else "add"}


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(prog="tidal.py", description="generic TIDAL JSON CLI")
    subcommands = command.add_subparsers(dest="command", required=True)

    subcommands.add_parser("auth-login", help="interactive OAuth setup")
    subcommands.add_parser("auth-status", help="show session status")
    subcommands.add_parser("me", help="show account summary")

    resolve = subcommands.add_parser("resolve", help="parse TIDAL ids or URLs")
    resolve.add_argument("values", nargs="+", help="ids, URLs, or kind:id references")
    resolve.add_argument("--kind", choices=[*RESOURCE_KINDS, "auto"], default="auto")
    resolve.add_argument("--fetch", action="store_true", help="also fetch resource metadata using the current session")

    search = subcommands.add_parser("search", help="search TIDAL")
    search.add_argument("--type", choices=[*RESOURCE_KINDS, "all"], default="all")
    search.add_argument("--query", required=True)
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)

    playlists = subcommands.add_parser("list-playlists", help="list the current user's playlists")
    playlists.add_argument("--limit", type=int, default=50)
    playlists.add_argument("--offset", type=int, default=0)

    tracks = subcommands.add_parser("playlist-tracks", help="list tracks from a playlist")
    tracks.add_argument("playlist")
    tracks.add_argument("--limit", type=int, default=100)
    tracks.add_argument("--offset", type=int, default=0)

    favorites = subcommands.add_parser("favorites", help="list favorite items")
    favorites.add_argument("--type", choices=RESOURCE_KINDS, required=True)
    favorites.add_argument("--limit", type=int, default=50)
    favorites.add_argument("--offset", type=int, default=0)

    create = subcommands.add_parser("create-playlist", help="create a playlist")
    create.add_argument("--title", required=True)
    create.add_argument("--description", default="")
    create.add_argument("--confirm-write", action="store_true")

    rename = subcommands.add_parser("rename-playlist", help="rename or edit a playlist")
    rename.add_argument("playlist")
    rename.add_argument("--title")
    rename.add_argument("--description")
    rename.add_argument("--confirm-write", action="store_true")

    delete = subcommands.add_parser("delete-playlist", help="delete a playlist")
    delete.add_argument("playlist")
    delete.add_argument("--confirm-write", action="store_true")

    add = subcommands.add_parser("add-tracks", help="add tracks to a playlist")
    add.add_argument("playlist")
    add.add_argument("--track", action="append", help="track id, URL, or track:id; repeatable or comma-separated")
    add.add_argument("--position", type=int, default=-1)
    add.add_argument("--allow-duplicates", action="store_true")
    add.add_argument("--confirm-write", action="store_true")

    remove = subcommands.add_parser("remove-tracks", help="remove tracks from a playlist")
    remove.add_argument("playlist")
    remove.add_argument("--track", action="append", help="track id, URL, or track:id; repeatable or comma-separated")
    remove.add_argument("--index", action="append", help="0-based playlist item index; repeatable or comma-separated")
    remove.add_argument("--all-matches", action="store_true", help="remove every matching occurrence for --track")
    remove.add_argument("--confirm-write", action="store_true")

    reorder = subcommands.add_parser("reorder-tracks", help="move tracks inside a playlist")
    reorder.add_argument("playlist")
    reorder.add_argument("--track", action="append", help="single track id/url for first-match move")
    reorder.add_argument("--index", action="append", help="one or more 0-based playlist item indices")
    reorder.add_argument("--position", type=int, required=True)
    reorder.add_argument("--confirm-write", action="store_true")

    favorite_add = subcommands.add_parser("favorite-add", help="favorite an item")
    favorite_add.add_argument("--type", choices=RESOURCE_KINDS, required=True)
    favorite_add.add_argument("--item", action="append", help="item id, URL, or kind:id; repeatable or comma-separated")
    favorite_add.add_argument("--confirm-write", action="store_true")

    favorite_remove = subcommands.add_parser("favorite-remove", help="unfavorite an item")
    favorite_remove.add_argument("--type", choices=RESOURCE_KINDS, required=True)
    favorite_remove.add_argument("--item", action="append", help="single item id, URL, or kind:id")
    favorite_remove.add_argument("--confirm-write", action="store_true")
    return command


def dispatch(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "auth-login":
        return save_session_interactive()
    if args.command == "auth-status":
        return session_status()
    if args.command == "me":
        session, path = load_session(require_login=True)
        return {"session_file": str(path), "user": me_to_json(session.user)}
    if args.command == "resolve":
        return resolve_many(args.values, None if args.kind == "auto" else args.kind, args.fetch)
    if args.command == "search":
        return search_items(args)
    if args.command == "list-playlists":
        args.limit = clamp_limit(args.limit, 500)
        return list_playlists(args)
    if args.command == "playlist-tracks":
        args.limit = clamp_limit(args.limit, 500)
        return playlist_tracks(args)
    if args.command == "favorites":
        args.limit = clamp_limit(args.limit, 500)
        return list_favorites(args)
    if args.command == "create-playlist":
        return create_playlist(args)
    if args.command == "rename-playlist":
        return rename_playlist(args)
    if args.command == "delete-playlist":
        return delete_playlist(args)
    if args.command == "add-tracks":
        return add_tracks(args)
    if args.command == "remove-tracks":
        return remove_tracks(args)
    if args.command == "reorder-tracks":
        return reorder_tracks(args)
    if args.command == "favorite-add":
        return favorite_mutation(args, remove=False)
    if args.command == "favorite-remove":
        return favorite_mutation(args, remove=True)
    raise ValueError(f"unsupported command: {args.command}")


def main() -> None:
    try:
        payload = dispatch(parser().parse_args())
        sys.stdout.buffer.write((json.dumps(jsonable(payload), ensure_ascii=False, indent=2) + "\n").encode("utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(2) from error
    except Exception as error:
        print(f"TIDAL command failed: {type(error).__name__}: {error}", file=sys.stderr)
        raise SystemExit(1) from error


if __name__ == "__main__":
    main()
