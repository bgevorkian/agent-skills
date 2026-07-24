# Contributing

## Add a skill

1. Create `skills/<skill-name>/SKILL.md` following the [Agent Skills specification](https://agentskills.io/specification).
2. Use lowercase letters, digits, and hyphens for `name` (maximum 64 characters).
3. Write a specific `description` that states both capability and activation conditions.
4. Put executable helpers in `scripts/`, detailed guidance in `references/`, and static resources in `assets/`.
5. Document dependencies and platform requirements.
6. Add tests for regressions and edge cases.
7. Add the skill to the root README and `site/index.html`.

## Safety checklist

Before publishing:

- no tokens, API keys, passwords, cookies, private keys, or session files;
- no personal absolute paths;
- no internal hostnames, databases, proprietary URLs, or employer-specific instructions;
- source/user files are never committed;
- destructive actions require explicit confirmation;
- generated caches and output artifacts are excluded.

Run validation:

```bash
uv run --python 3.13 scripts/validate_skills.py
```

Then manually review the diff:

```bash
git diff --check
git status --short
```

## Pull requests

Keep one logical skill/change per pull request. Explain the use case, supported systems, dependencies, tests, and any known limitations.
