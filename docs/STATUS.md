# Project status

Last updated: 2026-07-26

## Repository

- Public repo: https://github.com/bgevorkian/agent-skills
- GitHub Pages: https://bgevorkian.github.io/agent-skills/
- Published and validated: 10 skills in the live catalog, including `video-to-notes`.

## Current release batch

Secure-secret decision: public skills expose only generic runtime inputs. User-specific static or dynamic profiles, hosts and secret-manager references remain private; only the selected profile is injected into one child process. The author's concrete implementation uses per-profile Proton Pass pointer files, while the public method remains provider-neutral.

User-approved public generic skills:

- `mssql-safe`: reads plus controlled writes.
- `trino-readonly`.
- `prefect-ops`: controlled writes.
- `telegram-user`: controlled writes, generic Telethon config.
- `youtrack`: one combined generic issues/comments/articles skill with controlled writes.
- `tidal`: generic explicit user-requested account operations only.

Safety decision: every mutation must require both a dedicated `*_ALLOW_WRITE=true` environment variable and an explicit `--confirm-write` CLI flag. No internal hosts, profiles, company examples, personal paths, credentials, or generated personal artifacts may be published.

TIDAL decision: do not publish recommendation, similar-playlist, vibe/BPM/key/energy classification, or automatic playlist sorting. The public skill handles explicit search/library/playlist/favorite tasks only.

Publication order was database skills first, then services; all passed one final integrated audit.

## Completed implementation batch

The five background builds completed successfully:

- `mssql-safe` and `trino-readonly`.
- `prefect-ops`.
- `telegram-user`.
- combined `youtrack`.
- generic explicit-task-only `tidal`.

Main-session audit completed:

- all 9 repository skills pass the Agent Skills validator;
- every new and existing unit/regression test passes;
- write commands were manually checked for the environment + `--confirm-write` double gate;
- security scan found no tokens, private keys, personal paths, internal infrastructure names, or personal TIDAL artifacts in 38 skill files;
- Prefect API tokens were restricted to the `PREFECT_API_KEY` environment variable (no CLI token flag);
- README, CI workflows and the 9-card Pages catalog were updated;
- the full Pages site was rendered and visually inspected.

## Release status

The generic operations/account batch was released in commit `1c2421a`. `video-to-notes` was released in commit `d835e40`. Validation and Pages workflows completed successfully, the live catalog exposes all 10 skills, the public SKILL URL returns HTTP 200, and the local checkout was clean after deployment verification. A matching `a/` SVG favicon was previewed locally and approved before publication.

## Video-to-notes batch

User approved the public name `video-to-notes` and dual Markdown + searchable PDF output. The skill must be described as a multimodal video-understanding pipeline, not simple speech-to-text: it combines native captions or optional faster-whisper transcription with bounded frame extraction, 64-bit dHash deduplication, and visual recovery of visible code, terminals, slides, diagrams, and UI steps.

Implementation includes deterministic preparation, optional local transcription, Unicode/Cyrillic PDF rendering, a model-neutral visual-analysis contract, prompt-injection/privacy guidance, subprocess timeouts and download/frame bounds. Offline tests cover transcript parsing, filename/command safety, dHash selection, transcription gating, manifest updates, Markdown sanitization, and searchable PDF output.

Publication completed: the full 10-skill validator/tests and Ruff passed, the security scan was clean, the 10-card site was rendered and reviewed, both GitHub workflows succeeded, and live HTTP content was verified.

## Never publish as-is

- Internal `clickhouse-query`, `pg`, `mssql`, `trino`, `prefect`, YouTrack profiles, and SSH inventory.
- `ssh-hosts` under any circumstances.
- Existing TIDAL recommendation/vibe skills until separately redesigned and approved.
- Private KB/Qdrant configuration without a full generic redesign.
