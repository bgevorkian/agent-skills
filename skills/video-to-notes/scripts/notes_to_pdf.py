#!/usr/bin/env python3
"""Render Markdown video notes as a searchable Unicode PDF."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

DANGEROUS_HTML_RE = re.compile(
    r"<\s*/?\s*(?:script|iframe|object|embed|form|input|button|textarea|select|link|meta|img)\b[^>]*>",
    re.IGNORECASE,
)
MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^\n)]*\)")
DEFAULT_CSS = """
@page { size: A4; }
body {
  font-family: sans-serif;
  font-size: 10.5pt;
  line-height: 1.48;
  color: #161713;
  background: #ffffff;
}
h1, h2, h3, h4 { font-family: sans-serif; font-weight: bold; page-break-after: avoid; }
h1 { font-size: 23pt; margin: 0 0 16pt; border-bottom: 2px solid #b8e900; padding-bottom: 8pt; }
h2 { font-size: 16pt; margin-top: 18pt; color: #252720; }
h3 { font-size: 12.5pt; margin-top: 14pt; }
p, li { orphans: 3; widows: 3; }
a { color: #3b5900; text-decoration: underline; }
blockquote { border-left: 3px solid #b8e900; margin-left: 0; padding-left: 12pt; color: #4c4e47; }
pre {
  font-family: monospace;
  font-size: 8.3pt;
  line-height: 1.35;
  white-space: pre-wrap;
  word-break: break-all;
  background: #f2f3ed;
  border: 1px solid #d8d9d2;
  padding: 9pt;
  page-break-inside: avoid;
}
code { font-family: monospace; background: #f2f3ed; padding: 1pt 3pt; }
pre code { padding: 0; background: transparent; }
table { border-collapse: collapse; width: 100%; margin: 8pt 0 12pt; font-size: 9pt; }
th, td { border: 1px solid #cfd0ca; padding: 5pt; vertical-align: top; }
th { background: #eceee4; font-weight: bold; }
hr { color: #cfd0ca; margin: 16pt 0; }
"""


class PdfRenderError(RuntimeError):
    """User-facing PDF rendering failure."""


def output_path_for(markdown_path: Path) -> Path:
    return markdown_path.with_suffix(".pdf")


def strip_dangerous_html(markdown_text: str) -> str:
    cleaned = DANGEROUS_HTML_RE.sub("", markdown_text.replace("\x00", ""))
    return MARKDOWN_IMAGE_RE.sub(lambda match: f"[Image omitted: {match.group(1) or 'untitled'}]", cleaned)


def markdown_to_html(markdown_text: str, title: str) -> str:
    try:
        import markdown  # type: ignore
    except ImportError as exc:
        raise PdfRenderError(
            "Markdown rendering requires the 'markdown' package; run with `uv run --with markdown ...`"
        ) from exc
    safe_markdown = strip_dangerous_html(markdown_text)
    body = markdown.markdown(
        safe_markdown,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html5",
    )
    if not re.search(r"<h1\b", body, re.IGNORECASE):
        from html import escape

        body = f"<h1>{escape(title)}</h1>\n{body}"
    return f"<!doctype html><html><head><meta charset='utf-8'></head><body>{body}</body></html>"


def render_pdf(
    markdown_path: Path,
    output_path: Path,
    title: str | None = None,
    page_size: str = "a4",
    margin: float = 50,
    overwrite: bool = False,
) -> dict[str, Any]:
    if not markdown_path.is_file():
        raise PdfRenderError(f"Markdown file not found: {markdown_path}")
    if margin < 18:
        raise PdfRenderError("margin must be at least 18 points")
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise PdfRenderError(
            "PDF rendering requires PyMuPDF; run with `uv run --with pymupdf ...`"
        ) from exc

    markdown_text = markdown_path.read_text(encoding="utf-8-sig", errors="strict")
    if not markdown_text.strip():
        raise PdfRenderError("Markdown file is empty")
    document_title = title or markdown_path.name.removesuffix(".notes.md").removesuffix(".md")
    html_text = markdown_to_html(markdown_text, document_title)

    try:
        media_box = fitz.paper_rect(page_size.lower())
    except Exception as exc:
        raise PdfRenderError(f"unsupported page size: {page_size}") from exc
    content_box = fitz.Rect(
        margin,
        margin,
        media_box.width - margin,
        media_box.height - margin,
    )
    if content_box.is_empty:
        raise PdfRenderError("margin leaves no printable area")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        if not overwrite:
            raise PdfRenderError(f"output already exists: {output_path}; pass --overwrite to replace it")
        output_path.unlink()
    temporary = output_path.with_name(f".{output_path.name}.tmp.pdf")
    temporary.unlink(missing_ok=True)
    writer = None
    try:
        story = fitz.Story(html=html_text, user_css=DEFAULT_CSS)
        writer = fitz.DocumentWriter(str(temporary))
        more = True
        pages = 0
        while more:
            if pages >= 1000:
                raise PdfRenderError("rendering exceeded the 1000-page safety limit")
            device = writer.begin_page(media_box)
            more, _ = story.place(content_box)
            story.draw(device)
            writer.end_page()
            pages += 1
        writer.close()
        writer = None

        with fitz.open(temporary) as document:
            extracted = "".join(page.get_text() for page in document)
            if document.page_count < 1 or len(extracted.strip()) < 10:
                raise PdfRenderError("generated PDF contains too little searchable text")
            metadata = document.metadata or {}
            metadata.update({"title": document_title, "creator": "video-to-notes", "producer": "PyMuPDF"})
            document.set_metadata(metadata)
            document.save(output_path)
            page_count = document.page_count
            text_characters = len(extracted)
        temporary.unlink(missing_ok=True)
    except PdfRenderError:
        if writer is not None:
            writer.close()
        temporary.unlink(missing_ok=True)
        raise
    except Exception as exc:
        if writer is not None:
            writer.close()
        temporary.unlink(missing_ok=True)
        raise PdfRenderError(f"PDF rendering failed: {exc}") from exc

    return {
        "markdown": str(markdown_path),
        "pdf": str(output_path),
        "pages": page_count,
        "searchable_text_characters": text_characters,
        "title": document_title,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render .notes.md as a searchable Unicode PDF.")
    parser.add_argument("markdown", type=Path, help="input Markdown notes")
    parser.add_argument("--output", type=Path, help="output PDF path; defaults next to Markdown")
    parser.add_argument("--title", help="PDF title metadata and fallback H1")
    parser.add_argument("--page-size", default="a4", choices=["a4", "letter"])
    parser.add_argument("--margin", type=float, default=50, help="page margin in PDF points")
    parser.add_argument("--overwrite", action="store_true", help="replace an existing output PDF")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    markdown_path = args.markdown.expanduser().resolve()
    output_path = (args.output.expanduser().resolve() if args.output else output_path_for(markdown_path))
    if output_path == markdown_path:
        parser.error("output path must differ from the Markdown input")
    try:
        result = render_pdf(markdown_path, output_path, args.title, args.page_size, args.margin, args.overwrite)
    except (PdfRenderError, OSError, UnicodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, **result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
