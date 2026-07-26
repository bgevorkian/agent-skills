from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from pypdf import PdfReader, PdfWriter

PRINT_STYLE = r"""
@page { size: A4; margin: 16mm 14mm 18mm; }
html, body { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
img, svg { max-width: 100%; height: auto; break-inside: avoid; page-break-inside: avoid; }
p { hyphens: auto; -webkit-hyphens: auto; }
h1, h2, h3, h4 { break-after: avoid; page-break-after: avoid; }
body.__epub_image_page {
  margin: 0 !important; padding: 0 !important; width: 182mm !important;
  height: 255mm !important; min-height: 255mm !important; overflow: hidden !important;
  display: flex !important; align-items: center !important; justify-content: center !important;
}
body.__epub_image_page > * {
  margin: 0 !important; padding: 0 !important; width: 100% !important; height: 100% !important;
  display: flex !important; align-items: center !important; justify-content: center !important;
}
body.__epub_image_page img, body.__epub_image_page svg {
  display: block !important; margin: auto !important; width: auto !important; height: auto !important;
  max-width: 180mm !important; max-height: 253mm !important; object-fit: contain !important;
}
"""

MAX_EPUB_FILES = 10_000
MAX_EPUB_SIZE = 512 * 1024 * 1024
WORK_MARKER = ".epub-ai-translate-owned"


def contained_path(root: Path, relative: str | Path) -> Path:
    root = root.resolve()
    target = (root / relative).resolve()
    if target != root and root not in target.parents:
        raise RuntimeError(f"EPUB path escapes the book directory: {relative}")
    return target


def safe_extract_epub(archive: zipfile.ZipFile, destination: Path) -> None:
    entries = archive.infolist()
    if len(entries) > MAX_EPUB_FILES or sum(item.file_size for item in entries) > MAX_EPUB_SIZE:
        raise RuntimeError("EPUB is too large to extract safely")
    destination.mkdir(parents=True, exist_ok=True)
    for item in entries:
        target = contained_path(destination, item.filename)
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with archive.open(item) as source, target.open("wb") as output:
            shutil.copyfileobj(source, output)


def prepare_work_dir(work: Path, restart: bool, protected: tuple[Path, ...]) -> Path:
    work = work.resolve()
    for path in protected:
        path = path.resolve()
        if path == work or work in path.parents:
            raise RuntimeError(f"work directory contains a protected input/output path: {path}")
    marker = work / WORK_MARKER
    if restart and work.exists():
        if not marker.is_file():
            raise RuntimeError(f"refusing to delete an unowned work directory: {work}")
        shutil.rmtree(work)
    if work.exists() and not marker.exists() and any(work.iterdir()):
        raise RuntimeError(f"refusing to use a non-empty unowned work directory: {work}")
    work.mkdir(parents=True, exist_ok=True)
    marker.touch(exist_ok=True)
    return work


def find_chrome() -> Path:
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
        Path(r"C:\Program Files\Microsoft\Edge\Application\msedge.exe"),
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/chromium"),
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Chrome or Edge executable was not found; pass --chrome")


def spine_documents(book: Path) -> list[Path]:
    container = ET.parse(book / "META-INF" / "container.xml")
    rootfile = container.find(".//{*}rootfile")
    if rootfile is None:
        raise RuntimeError("EPUB rootfile not found")
    opf = contained_path(book, rootfile.attrib["full-path"])
    package = ET.parse(opf).getroot()
    base = opf.parent
    manifest = {
        item.attrib["id"]: (
            contained_path(book, base.relative_to(book) / item.attrib["href"]),
            item.attrib.get("media-type", ""),
        )
        for item in package.findall(".//{*}manifest/{*}item")
    }
    documents: list[Path] = []
    for itemref in package.findall(".//{*}spine/{*}itemref"):
        entry = manifest.get(itemref.attrib.get("idref", ""))
        if entry and entry[1] in {"application/xhtml+xml", "text/html"}:
            documents.append(entry[0])
    return documents


def patch_for_print(path: Path) -> None:
    soup = BeautifulSoup(path.read_bytes(), "html.parser")
    for tag in soup.find_all(["script", "iframe", "object", "embed", "base"]):
        tag.decompose()
    for tag in soup.find_all(True):
        for attribute in list(tag.attrs):
            if attribute.lower().startswith("on"):
                del tag.attrs[attribute]
        for attribute in ("href", "src", "poster", "action", "formaction", "xlink:href"):
            value = tag.get(attribute)
            if isinstance(value, str) and (
                value.startswith(("/", "//"))
                or re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", value)
            ):
                del tag.attrs[attribute]
        if tag.get("http-equiv"):
            tag.decompose()
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            style_tag.string.replace_with(re.sub(
                r"@import\s+[^;]+;|url\(\s*['\"]?(?:[a-z]+:|//|/)[^)]+\)",
                "",
                style_tag.string,
                flags=re.I,
            ))
    body = soup.body
    if body is not None and not body.get_text(" ", strip=True) and body.find(["img", "svg"]):
        classes = list(body.get("class", []))
        if "__epub_image_page" not in classes:
            classes.append("__epub_image_page")
        body["class"] = classes
    style = soup.new_tag("style")
    style.string = PRINT_STYLE
    head = soup.head
    if head is None:
        head = soup.new_tag("head")
        soup.insert(0, head)
    csp = soup.new_tag("meta")
    csp["http-equiv"] = "Content-Security-Policy"
    csp["content"] = "default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:"
    head.append(csp)
    head.append(style)
    path.write_text(str(soup), encoding="utf-8")


def convert(epub: Path, pdf: Path, chrome: Path | None = None) -> None:
    epub = epub.resolve()
    pdf = pdf.resolve()
    chrome = (chrome or find_chrome()).resolve()
    if epub == pdf:
        raise ValueError("input EPUB and output PDF must be different files")
    pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="epub_pdf_") as temp:
        root = Path(temp)
        book = root / "book"
        parts = root / "parts"
        book.mkdir()
        parts.mkdir()
        with zipfile.ZipFile(epub) as archive:
            safe_extract_epub(archive, book)

        documents = spine_documents(book)
        writer = PdfWriter()
        for index, document in enumerate(documents, 1):
            patch_for_print(document)
            part = parts / f"{index:04d}.pdf"
            result = subprocess.run(
                [
                    str(chrome),
                    "--headless",
                    "--disable-gpu",
                    "--disable-javascript",
                    "--disable-background-networking",
                    "--disable-extensions",
                    "--no-first-run",
                    "--no-pdf-header-footer",
                    f"--user-data-dir={root / 'chrome-profile'}",
                    f"--print-to-pdf={part}",
                    document.as_uri(),
                ],
                capture_output=True,
                text=True,
                timeout=180,
            )
            if result.returncode != 0 or not part.exists() or part.read_bytes()[:4] != b"%PDF":
                raise RuntimeError(f"Chrome failed on {document.name}: {result.stderr[-2000:]}")
            reader = PdfReader(str(part))
            for page in reader.pages:
                writer.add_page(page)
            print(f"[{index}/{len(documents)}] PDF {document.name}: {len(reader.pages)} page(s)", flush=True)

        temporary_output = pdf.with_suffix(pdf.suffix + ".tmp")
        with temporary_output.open("wb") as stream:
            writer.write(stream)
        temporary_output.replace(pdf)
        if pdf.read_bytes()[:4] != b"%PDF":
            raise RuntimeError("merged PDF validation failed")


def main() -> None:
    parser = argparse.ArgumentParser(description="Convert EPUB to PDF with isolated per-document styles")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--chrome", type=Path)
    args = parser.parse_args()
    convert(args.input, args.output, args.chrome)
    pages = len(PdfReader(str(args.output)).pages)
    print(f"SUCCESS: {args.output.resolve()} | pages={pages} | size={args.output.stat().st_size}")


if __name__ == "__main__":
    main()
