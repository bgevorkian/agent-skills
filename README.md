# Agent Skills by bgevorkian

Reusable, open-source [Agent Skills](https://agentskills.io/) for Pi and other compatible agent systems.

**Catalog:** https://bgevorkian.github.io/agent-skills/

## Skills

| Skill | What it does | Requirements |
|---|---|---|
| [`epub-ai-translate`](skills/epub-ai-translate/) | Literary AI translation of user-provided EPUB or text-layer PDF books into Russian. Preserves images, supports checkpoints and glossaries, builds book-quality PDFs, and performs full-page vision layout QA. | Pi CLI, `uv`, Python 3.13, Chrome/Edge |
| [`video-to-notes`](skills/video-to-notes/) | Convert local videos or supported URLs into Markdown notes and searchable PDFs using subtitles/optional Whisper plus perceptually deduplicated visual frames—capturing on-screen code, terminals, slides and UI, not merely speech-to-text. | `uv`, Python 3.11+, `ffmpeg`, `Pillow`; optional `yt-dlp`, `faster-whisper`, `markdown`, `pymupdf` |
| [`clickhouse-readonly`](skills/clickhouse-readonly/) | Infrastructure-neutral read-only ClickHouse query/list/schema CLI with JSON output, TLS defaults, result limits, local SQL guards, and server `readonly=1`. | `uv`, Python 3.11+, `clickhouse-connect` |
| [`postgres-readonly`](skills/postgres-readonly/) | Safe single-host or bounded multi-host PostgreSQL queries with JSON output, standard `PG*` configuration, TLS, SQL guards, and read-only transactions. | `uv`, Python 3.11+, `asyncpg` |
| [`mssql-safe`](skills/mssql-safe/) | Generic SQL Server inspection/query CLI plus doubly gated DDL/DML execution. | `uv`, Python 3.11+, `pymssql` |
| [`trino-readonly`](skills/trino-readonly/) | Guarded Trino/Iceberg queries and catalog/schema/table inspection with generic TLS/auth configuration. | `uv`, Python 3.11+, `trino` |
| [`prefect-ops`](skills/prefect-ops/) | Inspect Prefect 3 runs, logs, deployments, schedules, variables and automations; operational changes are double-gated. | `uv`, Python 3.11+ |
| [`telegram-user`](skills/telegram-user/) | Generic Telethon user-account CLI for dialogs, messages, search, folders and contacts with controlled mutations. | `uv`, Python 3.11+, `telethon` |
| [`youtrack`](skills/youtrack/) | Generic YouTrack issues, comments, projects, users, field schema and Knowledge Base articles with controlled writes. | `uv`, Python 3.11+ |
| [`tidal`](skills/tidal/) | Explicit TIDAL account tasks: auth, search, library, playlists and favorites. No recommendations, vibe classification or auto-sorting. | `uv`, Python 3.13+, `tidalapi` |

## Install

### Shared Agent Skills directory

Clone the repository and copy or symlink the skill you need into the shared skills directory used by your agent:

```bash
git clone https://github.com/bgevorkian/agent-skills.git
mkdir -p ~/.agents/skills
cp -R agent-skills/skills/<skill-name> ~/.agents/skills/
```

On Windows PowerShell:

```powershell
git clone https://github.com/bgevorkian/agent-skills.git
New-Item -ItemType Directory -Force "$HOME/.agents/skills" | Out-Null
Copy-Item -Recurse agent-skills/skills/<skill-name> "$HOME/.agents/skills/"
```

Pi discovers `~/.agents/skills/` and `~/.pi/agent/skills/`. For another harness, use its documented Agent Skills directory or load the skill explicitly.

## Secure secret profiles

Skills use generic runtime inputs; user-specific hosts, profile names and secret references stay outside the repository. Ask which secret manager the user prefers and inject only the selected local profile into one child process. Proton Pass is the author's method, not a dependency.

Read [Secure secret profiles](docs/secure-secrets.md) before configuring credentials or session files.

### Pi command

After restarting Pi, force-load a skill with:

```text
/skill:epub-ai-translate
/skill:video-to-notes
/skill:clickhouse-readonly
/skill:postgres-readonly
/skill:mssql-safe
/skill:trino-readonly
/skill:prefect-ops
/skill:telegram-user
/skill:youtrack
/skill:tidal
```

Or ask naturally; each description is designed for automatic activation.

## Design principles

- Conform to the Agent Skills `SKILL.md` structure.
- Prefer full, context-aware AI models when quality matters.
- Keep long jobs resumable and source files immutable.
- Validate model output before writing artifacts.
- Run deterministic checks plus a separate vision QA for document layout.
- Never publish secrets, machine-specific credentials, or proprietary infrastructure details.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Each skill must pass:

```bash
uv run --python 3.13 scripts/validate_skills.py
```

## License

MIT — see [LICENSE](LICENSE). Individual bundled assets may declare their own licenses.
