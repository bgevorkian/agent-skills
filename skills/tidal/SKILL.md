---
name: tidal
description: Generic TIDAL account JSON CLI for explicit user-requested tasks: OAuth setup/status, me, search, playlist inspection, favorites, id/URL resolution, and tightly gated playlist/favorite writes. Use when the user explicitly asks to work with TIDAL itself, not for recommendations, similarity, mood, vibe, BPM, key, or auto-sorting.
compatibility: Python 3.13+, uv, network access to TIDAL, and tidalapi. Session data is loaded from TIDAL_SESSION_FILE or a generic per-user data directory.
license: MIT
metadata:
  author: bgevorkian
  version: "1.0.0"
---

# TIDAL

Generic TIDAL account skill for direct, explicit tasks only.

It can:

- run interactive OAuth setup and show auth status;
- show the current account summary;
- search tracks, albums, artists, and playlists;
- list user playlists and playlist tracks;
- list favorites when supported by the installed `tidalapi`;
- resolve TIDAL ids and URLs;
- create, rename, delete playlists;
- add, remove, and reorder playlist tracks;
- favorite and unfavorite supported items.

It does **not** do recommendations, radio, similarity, mood, BPM, key, energy, vibe classification, or automatic playlist sorting.

## Safety contract

Every TIDAL account mutation requires **both**:

1. `TIDAL_ALLOW_WRITE=true`
2. explicit `--confirm-write`

Without both, writes fail locally before any API call.

Never print or commit session file contents.

## Session location

Session lookup order:

1. `TIDAL_SESSION_FILE`
2. generic per-user data file:
   - Windows: `%APPDATA%/agent-skills/tidal/session.json`
   - macOS: `~/Library/Application Support/agent-skills/tidal/session.json`
   - Linux: `${XDG_DATA_HOME:-~/.local/share}/agent-skills/tidal/session.json`

## Secret setup

Follow [Secure secret profiles](https://github.com/bgevorkian/agent-skills/blob/main/docs/secure-secrets.md). Treat the TIDAL session as a credential file, not an ordinary environment variable: keep it outside the skill with private permissions and never print or commit its contents. Ask before changing authentication or materializing a temporary file from a secret manager.

## Run

From this skill directory:

```bash
uv run --python 3.13 --with tidalapi python scripts/tidal.py auth-login
uv run --python 3.13 --with tidalapi python scripts/tidal.py auth-status
uv run --python 3.13 --with tidalapi python scripts/tidal.py me
uv run --python 3.13 --with tidalapi python scripts/tidal.py search --type track --query "Massive Attack" --limit 10
uv run --python 3.13 --with tidalapi python scripts/tidal.py resolve "https://tidal.com/browse/playlist/00000000-0000-0000-0000-000000000000"
uv run --python 3.13 --with tidalapi python scripts/tidal.py list-playlists --limit 50 --offset 0
uv run --python 3.13 --with tidalapi python scripts/tidal.py playlist-tracks playlist:00000000-0000-0000-0000-000000000000 --limit 100
uv run --python 3.13 --with tidalapi python scripts/tidal.py favorites --type track --limit 50
```

## Write examples

```bash
TIDAL_ALLOW_WRITE=true uv run --python 3.13 --with tidalapi python scripts/tidal.py create-playlist --title "Inbox" --description "Manual playlist" --confirm-write
TIDAL_ALLOW_WRITE=true uv run --python 3.13 --with tidalapi python scripts/tidal.py rename-playlist playlist:00000000-0000-0000-0000-000000000000 --title "Inbox 2" --confirm-write
TIDAL_ALLOW_WRITE=true uv run --python 3.13 --with tidalapi python scripts/tidal.py add-tracks playlist:00000000-0000-0000-0000-000000000000 --track track:12345 --track track:67890 --confirm-write
TIDAL_ALLOW_WRITE=true uv run --python 3.13 --with tidalapi python scripts/tidal.py remove-tracks playlist:00000000-0000-0000-0000-000000000000 --index 0,1 --confirm-write
TIDAL_ALLOW_WRITE=true uv run --python 3.13 --with tidalapi python scripts/tidal.py reorder-tracks playlist:00000000-0000-0000-0000-000000000000 --index 3 --position 0 --confirm-write
TIDAL_ALLOW_WRITE=true uv run --python 3.13 --with tidalapi python scripts/tidal.py favorite-add --type album --item album:54321 --confirm-write
TIDAL_ALLOW_WRITE=true uv run --python 3.13 --with tidalapi python scripts/tidal.py favorite-remove --type album --item album:54321 --confirm-write
```

## Notes

- Output is UTF-8 JSON.
- Limits and offsets are supported on read commands.
- `resolve` accepts TIDAL URLs, `kind:id`, `kind/id`, or explicit `--kind`.
- Raw numeric ids are ambiguous without a known kind.
- `favorite-remove` is intentionally single-item to avoid accidental bulk deletes.

## Tests

```bash
uv run --python 3.13 --with tidalapi python tests/test_tidal.py
```
