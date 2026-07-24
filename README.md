# Agent Skills by bgevorkian

Reusable, open-source [Agent Skills](https://agentskills.io/) for Pi and other compatible agent systems.

**Catalog:** https://bgevorkian.github.io/agent-skills/

## Skills

| Skill | What it does | Requirements |
|---|---|---|
| [`epub-ai-translate`](skills/epub-ai-translate/) | Literary AI translation of user-provided EPUB or text-layer PDF books into Russian. Preserves images, supports checkpoints and glossaries, builds book-quality PDFs, and performs full-page vision layout QA. | Pi CLI, `uv`, Python 3.13, Chrome/Edge |

## Install

### Shared Agent Skills directory

Clone the repository and copy or symlink the skill you need into the shared skills directory used by your agent:

```bash
git clone https://github.com/bgevorkian/agent-skills.git
mkdir -p ~/.agents/skills
cp -R agent-skills/skills/epub-ai-translate ~/.agents/skills/
```

On Windows PowerShell:

```powershell
git clone https://github.com/bgevorkian/agent-skills.git
New-Item -ItemType Directory -Force "$HOME/.agents/skills" | Out-Null
Copy-Item -Recurse agent-skills/skills/epub-ai-translate "$HOME/.agents/skills/"
```

Pi discovers `~/.agents/skills/` and `~/.pi/agent/skills/`. For another harness, use its documented Agent Skills directory or load the skill explicitly.

### Pi command

After restarting Pi, force-load the skill with:

```text
/skill:epub-ai-translate
```

Or simply ask Pi to translate an EPUB/PDF book into Russian; the description is designed for automatic activation.

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
