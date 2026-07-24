# Project status

Last updated: 2026-07-24

## Repository

- Public repo: https://github.com/bgevorkian/agent-skills
- GitHub Pages: https://bgevorkian.github.io/agent-skills/
- Local checkout: `C:\Users\bgevorkian\agent-skills`
- Published and validated: 9 skills in the live catalog; the next approved package is `video-to-notes`.

## Current release batch

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

Released in commit `1c2421a` (`feat: publish generic operations and account skills`). Both GitHub Actions workflows completed successfully and the live Pages catalog exposes all 9 skills. A matching `a/` SVG favicon was previewed locally and approved before publication.

## Video-to-notes batch

User approved the public name `video-to-notes` and dual Markdown + searchable PDF output. The skill must be described as a multimodal video-understanding pipeline, not simple speech-to-text: it combines native captions or optional faster-whisper transcription with bounded frame extraction, 64-bit dHash deduplication, and visual recovery of visible code, terminals, slides, diagrams, and UI steps.

Implementation includes deterministic preparation, optional local transcription, Unicode/Cyrillic PDF rendering, a model-neutral visual-analysis contract, prompt-injection/privacy guidance, subprocess timeouts and download/frame bounds. Offline tests cover transcript parsing, filename/command safety, dHash selection, transcription gating, manifest updates, Markdown sanitization, and searchable PDF output.

Publication checklist: run the full 10-skill validator/tests, security scan, render the 10-card site, review the complete diff, commit/push, watch both workflows, and verify the live catalog.

## Never publish as-is

- Internal `clickhouse-query`, `pg`, `mssql`, `trino`, `prefect`, YouTrack profiles, and SSH inventory.
- `ssh-hosts` under any circumstances.
- Existing TIDAL recommendation/vibe skills until separately redesigned and approved.
- Private KB/Qdrant configuration without a full generic redesign.
