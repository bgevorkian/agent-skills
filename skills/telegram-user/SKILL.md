---
name: telegram-user
description: Use Telethon against a user's own Telegram account through a UTF-8 JSON CLI for login, status, profile, dialogs, messages, search, saved messages, folders, contacts, and guarded mutations. Configure only with TELEGRAM_API_ID, TELEGRAM_API_HASH, and TELEGRAM_SESSION_FILE.
compatibility: Python 3.11+, uv, Telethon, interactive terminal access for login, and Telegram network access. The default session file lives in a generic per-user data directory unless TELEGRAM_SESSION_FILE is set.
license: MIT
metadata:
  author: bgevorkian
  version: "1.0.0"
---

# Telegram User

Generic Telegram user-account skill built on Telethon. It uses only environment-based configuration, prints UTF-8 JSON, keeps login explicit and interactive, and blocks writes unless both gates are enabled.

## Configuration

| Variable | Required | Default |
|---|---:|---|
| `TELEGRAM_API_ID` | for all network commands | none |
| `TELEGRAM_API_HASH` | for all network commands | none |
| `TELEGRAM_SESSION_FILE` | no | platform user-data path |
| `TELEGRAM_ALLOW_WRITE` | no | `false` |

Default session path:

- Windows: `%APPDATA%/telegram-user/telethon.session`
- Linux/macOS: `$XDG_DATA_HOME/telegram-user/telethon.session` or `~/.local/share/telegram-user/telethon.session`

Never commit session files or secrets.

## Run

From this skill directory:

```bash
uv run --python 3.13 --with telethon python scripts/tg.py status
uv run --python 3.13 --with telethon python scripts/tg.py login
uv run --python 3.13 --with telethon python scripts/tg.py me
uv run --python 3.13 --with telethon python scripts/tg.py dialogs --limit 50
uv run --python 3.13 --with telethon python scripts/tg.py messages me --limit 20
uv run --python 3.13 --with telethon python scripts/tg.py search "invoice" --chat me --limit 20
uv run --python 3.13 --with telethon python scripts/tg.py saved messages --limit 20
uv run --python 3.13 --with telethon python scripts/tg.py folders list
uv run --python 3.13 --with telethon python scripts/tg.py contacts list --limit 100
uv run --python 3.13 --with telethon python scripts/tg.py raw messages.GetDialogFiltersRequest '{}'
```

Optional wrapper:

```bash
uv run --python 3.13 --with telethon python scripts/login.py
```

Use `--help` on the root command or any subcommand.

## Write gate

These commands mutate Telegram state and require **both**:

1. `TELEGRAM_ALLOW_WRITE=true`
2. `--confirm-write`

Guarded operations:

- `send`, `edit`, `delete`
- `saved send`
- `folders add-peers`, `folders remove-peers`, `folders set-title`
- `contacts add`, `contacts delete`
- `raw` when the method is not confidently read-only

Read commands do not require the gate.

## Notes

- Login never prints codes, API hashes, session bytes, or secrets.
- Prompts are written to stderr so stdout stays machine-readable JSON.
- `raw` accepts inline JSON, `@file.json`, or `-` for stdin.
- Complex raw arguments may use Telethon-style type objects such as `{"_":"InputPeerSelf"}`.

## Tests

```bash
uv run --python 3.13 --with telethon python tests/test_tg.py
```
