from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup, NavigableString
from pypdf import PdfReader

from epub_to_pdf import convert as convert_to_pdf, find_chrome

DEFAULT_MODEL = "openai-codex/gpt-5.4"
DEFAULT_STYLE = "Polished literary Russian matching the source's age, register, tone, genre, dialogue style, and emotional nuance."
BASE_GLOSSARY = """Apply established Russian terminology for the work's franchise or genre. Keep trademarks, ISBNs, and URLs unchanged unless they form ordinary prose. Transliterate recurring personal and place names consistently."""

PROMPT = """You are a professional literary translator translating a user-provided book from {source_language} into {target_language}.
Translate ONLY the human-readable source text enclosed in every <t id="..."> element in the XHTML below.

Rules:
1. Return ONLY the complete transformed XHTML. No Markdown fences, explanations, preamble, or summary.
2. Preserve every <t> element and id exactly once and in the same order. Preserve every other XML/HTML tag, attribute, URL, and document structure.
3. Translate all text inside <t> naturally and fluently. Do not summarize, censor, omit, or add content.
4. Preserve paragraph flow, dialogue, capitalization intent, sound effects, emotional nuance, and the author's pacing.
5. Maintain consistent terminology and names throughout the book according to the shared glossary.
6. Do not translate publisher URLs, ISBNs, or trademark names unless they form ordinary prose.

Style:
{style}

Shared glossary and consistency rules:
{glossary}

File: {filename}

XHTML TO TRANSLATE:
{xhtml}
"""

PRINT_LOCK = threading.Lock()


def log(message: str) -> None:
    with PRINT_LOCK:
        print(message, flush=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned[:80] or "book"


def default_work_dir(source: Path) -> Path:
    root = Path(os.environ.get("LOCALAPPDATA", Path.home() / ".cache")) / "epub-ai-translate"
    suffix = hashlib.sha256(str(source.resolve()).encode("utf-8")).hexdigest()[:10]
    return root / f"{safe_name(source.stem)}-{suffix}"


def epub_root_and_docs(book: Path) -> tuple[Path, list[Path]]:
    container = ET.parse(book / "META-INF" / "container.xml")
    rootfile = container.find(".//{*}rootfile")
    if rootfile is None:
        raise RuntimeError("EPUB rootfile not found")
    opf = book / Path(rootfile.attrib["full-path"])
    package = ET.parse(opf).getroot()
    opf_dir = opf.parent
    documents: list[Path] = []
    for item in package.findall(".//{*}manifest/{*}item"):
        if item.attrib.get("media-type") in {"application/xhtml+xml", "text/html"}:
            documents.append((opf_dir / Path(item.attrib["href"])).resolve())
    return opf, documents


def prepare_tagged_xhtml(path: Path) -> tuple[BeautifulSoup, dict[str, tuple[str, str, str]]]:
    soup = BeautifulSoup(path.read_bytes(), "xml")
    records: dict[str, tuple[str, str, str]] = {}
    counter = 0
    for node in list(soup.find_all(string=True)):
        # Doctype, declarations, comments, and CDATA subclass NavigableString.
        # They are structure, not prose, and wrapping a Doctype creates two roots.
        if type(node) is not NavigableString or node.parent is None:
            continue
        if node.parent.name in {"style", "script", "code"}:
            continue
        match = re.match(r"^(\s*)(.*?)(\s*)$", str(node), flags=re.S)
        if match is None:
            continue
        prefix, core, suffix = match.groups()
        if not core or not re.search(r"[A-Za-z]", core):
            continue
        counter += 1
        marker = f"T{counter:04d}"
        tag = soup.new_tag("t")
        tag["id"] = marker
        tag.string = core
        node.replace_with(tag)
        records[marker] = (prefix, core, suffix)
    return soup, records


def clean_model_output(raw: str) -> str:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:html|xml|xhtml)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
    start, end = text.find("<"), text.rfind(">")
    if start < 0 or end <= start:
        raise ValueError("model returned no XHTML")
    return text[start : end + 1]


def call_model(pi: str, model: str, prompt: str, timeout: int = 600) -> str:
    environment = os.environ.copy()
    environment.update({"NO_COLOR": "1", "FORCE_COLOR": "0", "PYTHONIOENCODING": "utf-8"})
    result = subprocess.run(
        [pi, "-p", "--no-session", "--mode", "text", "--model", model, "--tools", ""],
        input=prompt,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        env=environment,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Pi exited {result.returncode}: {result.stderr[-1500:]}")
    return result.stdout


def marker_path(done_dir: Path, relative: Path) -> Path:
    key = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:20]
    return done_dir / f"{key}.json"


def translate_document(
    index: int,
    total: int,
    path: Path,
    book: Path,
    done_dir: Path,
    pairs_dir: Path,
    pi: str,
    model: str,
    source_language: str,
    target_language: str,
    target_code: str,
    style: str,
    glossary: str,
    retries: int,
) -> str:
    relative = path.relative_to(book)
    marker = marker_path(done_dir, relative)
    if marker.exists():
        return f"[{index}/{total}] skipped {relative}"

    soup, records = prepare_tagged_xhtml(path)
    if not records:
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"path": relative.as_posix(), "segments": 0}), encoding="utf-8")
        return f"[{index}/{total}] no text {relative}"

    prompt = PROMPT.format(
        source_language=source_language,
        target_language=target_language,
        style=style,
        glossary=glossary,
        filename=relative.as_posix(),
        xhtml=str(soup),
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            raw = call_model(pi, model, prompt)
            translated = BeautifulSoup(clean_model_output(raw), "xml")
            tags = translated.find_all("t")
            found = {str(tag.get("id")): tag for tag in tags if tag.get("id")}
            expected = set(records)
            if len(tags) != len(records) or set(found) != expected:
                missing = sorted(expected - set(found))[:8]
                extra = sorted(set(found) - expected)[:8]
                raise ValueError(
                    f"tag mismatch: expected={len(records)} found={len(tags)} missing={missing} extra={extra}"
                )

            pairs: list[dict[str, str]] = []
            for tag in soup.find_all("t"):
                marker_id = str(tag.get("id"))
                prefix, original, suffix = records[marker_id]
                target = found[marker_id].get_text().strip()
                if not target:
                    raise ValueError(f"empty translation for {marker_id}")
                pairs.append({"id": marker_id, "source": original, "target": target})
                tag.replace_with(NavigableString(prefix + target + suffix))

            html = soup.find("html")
            if html is not None:
                html["lang"] = target_code
                if html.has_attr("xml:lang"):
                    html["xml:lang"] = target_code
            path.write_text(str(soup), encoding="utf-8")

            done_dir.mkdir(parents=True, exist_ok=True)
            pairs_dir.mkdir(parents=True, exist_ok=True)
            payload = {"path": relative.as_posix(), "segments": len(records), "model": model}
            marker.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            (pairs_dir / marker.name).write_text(
                json.dumps({"path": relative.as_posix(), "pairs": pairs}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            return f"[{index}/{total}] translated {relative} ({len(records)} segments)"
        except Exception as error:
            last_error = error
            log(f"[{index}/{total}] retry {attempt}/{retries} for {relative}: {error}")
            time.sleep(2 * attempt)
    raise RuntimeError(f"failed to translate {relative}: {last_error}")


def update_language(opf: Path, target_code: str) -> None:
    tree = ET.parse(opf)
    for language in tree.getroot().findall(".//{*}metadata/{*}language"):
        language.text = target_code
    tree.write(opf, encoding="utf-8", xml_declaration=True)


def pack_epub(book: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.unlink(missing_ok=True)
    with zipfile.ZipFile(output, "w") as archive:
        mimetype = book / "mimetype"
        if mimetype.exists():
            archive.write(mimetype, "mimetype", compress_type=zipfile.ZIP_STORED)
        for path in sorted(book.rglob("*")):
            if path.is_file() and path != mimetype:
                archive.write(path, path.relative_to(book).as_posix(), compress_type=zipfile.ZIP_DEFLATED)


def config_payload(args: argparse.Namespace, source: Path, glossary: str) -> dict[str, object]:
    return {
        "source": str(source.resolve()),
        "source_sha256": sha256_file(source),
        "source_language": args.source_language,
        "target_language": args.target_language,
        "target_code": args.target_code,
        "model": args.model,
        "style": args.style,
        "glossary_sha256": hashlib.sha256(glossary.encode("utf-8")).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Translate a user-provided EPUB into Russian via Pi and build EPUB/PDF output"
    )
    parser.add_argument("input", type=Path)
    parser.add_argument("--output-epub", type=Path)
    parser.add_argument("--output-pdf", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--glossary", type=Path)
    parser.add_argument("--source-language", default="English")
    parser.add_argument("--target-language", default="Russian")
    parser.add_argument("--target-code", default="ru")
    parser.add_argument("--style", default=DEFAULT_STYLE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--chrome", type=Path)
    parser.add_argument("--epub-only", action="store_true")
    parser.add_argument("--restart", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    source = args.input.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    if source.suffix.lower() != ".epub":
        raise ValueError("input must be an EPUB file")
    if not 1 <= args.workers <= 8:
        raise ValueError("--workers must be between 1 and 8")
    if not 1 <= args.retries <= 5:
        raise ValueError("--retries must be between 1 and 5")

    output_epub = (args.output_epub or source.with_name(f"{source.stem} — русский перевод.epub")).resolve()
    output_pdf = (args.output_pdf or source.with_name(f"{source.stem} — русский перевод.pdf")).resolve()
    for output in ([output_epub] if args.epub_only else [output_epub, output_pdf]):
        if output.exists() and not args.force:
            raise FileExistsError(f"output exists; pass --force to overwrite: {output}")

    glossary = BASE_GLOSSARY
    if args.glossary:
        glossary += "\n\n" + args.glossary.expanduser().read_text(encoding="utf-8")
    work = (args.work_dir or default_work_dir(source)).expanduser().resolve()
    if args.restart and work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    state_path = work / "state.json"
    expected_state = config_payload(args, source, glossary)
    if state_path.exists():
        existing_state = json.loads(state_path.read_text(encoding="utf-8"))
        if existing_state != expected_state:
            raise RuntimeError(f"checkpoint settings differ; inspect {state_path} and rerun with --restart")
    else:
        state_path.write_text(json.dumps(expected_state, ensure_ascii=False, indent=2), encoding="utf-8")

    book = work / "book"
    if not book.exists():
        with zipfile.ZipFile(source) as archive:
            archive.extractall(book)
    opf, documents = epub_root_and_docs(book)

    pi = shutil.which("pi.cmd") or shutil.which("pi")
    if not pi:
        raise FileNotFoundError("Pi CLI was not found in PATH")
    log(f"Translating {len(documents)} XHTML documents with {args.workers} workers via {args.model}")

    failures: list[str] = []
    done_dir = work / "done"
    pairs_dir = work / "translation-pairs"
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(
                translate_document,
                index,
                len(documents),
                document,
                book,
                done_dir,
                pairs_dir,
                pi,
                args.model,
                args.source_language,
                args.target_language,
                args.target_code,
                args.style,
                glossary,
                args.retries,
            ): document
            for index, document in enumerate(documents, 1)
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                log(future.result())
            except Exception as error:
                failures.append(str(error))
                log(f"ERROR: {error}")
    if failures:
        raise RuntimeError("Translation failures:\n" + "\n".join(failures))

    update_language(opf, args.target_code)
    full_text = " ".join(BeautifulSoup(path.read_bytes(), "xml").get_text(" ") for path in documents)
    cyrillic = len(re.findall(r"[А-Яа-яЁё]", full_text))
    latin = len(re.findall(r"[A-Za-z]", full_text))
    cyrillic_ratio = cyrillic / max(1, cyrillic + latin)
    log(f"Language validation: Cyrillic={cyrillic}, Latin={latin}, Cyrillic ratio={cyrillic_ratio:.1%}")
    if args.target_code.lower().startswith("ru") and (cyrillic < 100 or cyrillic_ratio < 0.70):
        raise RuntimeError("translated text failed Cyrillic coverage validation")

    pack_epub(book, output_epub)
    log(f"Built EPUB: {output_epub} ({output_epub.stat().st_size} bytes)")
    pages = None
    if not args.epub_only:
        chrome = args.chrome.expanduser() if args.chrome else find_chrome()
        convert_to_pdf(output_epub, output_pdf, chrome)
        reader = PdfReader(str(output_pdf))
        pages = len(reader.pages)
        if pages < 1 or output_pdf.stat().st_size < 10_000 or output_pdf.read_bytes()[:4] != b"%PDF":
            raise RuntimeError("PDF output validation failed")

    report = {
        "source": str(source),
        "output_epub": str(output_epub),
        "output_pdf": None if args.epub_only else str(output_pdf),
        "documents": len(documents),
        "cyrillic": cyrillic,
        "latin": latin,
        "cyrillic_ratio": cyrillic_ratio,
        "pdf_pages": pages,
        "model": args.model,
        "translation_pairs": str(pairs_dir),
    }
    (work / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"SUCCESS: {json.dumps(report, ensure_ascii=False)}")


if __name__ == "__main__":
    main()
