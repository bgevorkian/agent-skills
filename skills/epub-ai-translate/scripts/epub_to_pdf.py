from __future__ import annotations

import argparse
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
    opf = book / Path(rootfile.attrib["full-path"])
    package = ET.parse(opf).getroot()
    base = opf.parent
    manifest = {
        item.attrib["id"]: (
            (base / Path(item.attrib["href"])).resolve(),
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
    body = soup.body
    if body is not None and not body.get_text(" ", strip=True) and body.find(["img", "svg"]):
        classes = list(body.get("class", []))
        if "__epub_image_page" not in classes:
            classes.append("__epub_image_page")
        body["class"] = classes
    style = soup.new_tag("style")
    style.string = PRINT_STYLE
    if soup.head is None:
        head = soup.new_tag("head")
        soup.insert(0, head)
    soup.head.append(style)
    path.write_text(str(soup), encoding="utf-8")


def convert(epub: Path, pdf: Path, chrome: Path | None = None) -> None:
    epub = epub.resolve()
    pdf = pdf.resolve()
    chrome = (chrome or find_chrome()).resolve()
    pdf.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="epub_pdf_") as temp:
        root = Path(temp)
        book = root / "book"
        parts = root / "parts"
        book.mkdir()
        parts.mkdir()
        with zipfile.ZipFile(epub) as archive:
            archive.extractall(book)

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
                    "--no-pdf-header-footer",
                    "--allow-file-access-from-files",
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
