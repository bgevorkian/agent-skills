from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
LINK_RE = re.compile(r"\[[^]]*]\(([^)]+)\)")
FORBIDDEN = {
    "GitHub token": re.compile(r"gh[opusr]_[A-Za-z0-9_]{20,}"),
    "OpenAI-style key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"),
    "personal Windows path": re.compile(r"C:\\Users\\(?!<|%|USER|path)[^\\\s]+", re.I),
    "internal Spotware host": re.compile(r"(?:spotwa\.re|iforge\.it)", re.I),
}


def frontmatter(text: str) -> dict[str, str]:
    if not text.startswith("---\n"):
        return {}
    end = text.find("\n---\n", 4)
    if end < 0:
        return {}
    result: dict[str, str] = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line[:1].isspace():
            key, value = line.split(":", 1)
            result[key.strip()] = value.strip().strip("'\"")
    return result


def validate_skill(directory: Path) -> list[str]:
    errors: list[str] = []
    skill_file = directory / "SKILL.md"
    if not skill_file.exists():
        return [f"{directory}: missing SKILL.md"]
    text = skill_file.read_text(encoding="utf-8")
    metadata = frontmatter(text)
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if not name:
        errors.append(f"{skill_file}: missing name")
    elif not NAME_RE.fullmatch(name) or len(name) > 64:
        errors.append(f"{skill_file}: invalid name {name!r}")
    elif name != directory.name:
        errors.append(f"{skill_file}: name must match directory {directory.name!r}")
    if not description or len(description) > 1024:
        errors.append(f"{skill_file}: description must be 1..1024 characters")

    for match in LINK_RE.finditer(text):
        target = match.group(1).split("#", 1)[0]
        if not target or "://" in target or target.startswith(("#", "mailto:")):
            continue
        if not (directory / target).resolve().exists():
            errors.append(f"{skill_file}: broken relative link {target!r}")

    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            errors.append(f"{path}: generated cache must not be committed")
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for label, pattern in FORBIDDEN.items():
            if pattern.search(content):
                errors.append(f"{path}: possible {label}")
        if path.suffix == ".py":
            try:
                compile(content, str(path), "exec")
            except SyntaxError as error:
                errors.append(f"{path}:{error.lineno}: {error.msg}")
    return errors


def main() -> int:
    if not SKILLS.exists():
        print("skills directory does not exist", file=sys.stderr)
        return 1
    directories = sorted(path for path in SKILLS.iterdir() if path.is_dir())
    errors = [error for directory in directories for error in validate_skill(directory)]
    if errors:
        print("Validation failed:")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"Validated {len(directories)} skill(s): " + ", ".join(path.name for path in directories))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
