#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("video_to_notes_pdf", ROOT / "scripts" / "notes_to_pdf.py")
assert SPEC and SPEC.loader
pdf = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pdf
SPEC.loader.exec_module(pdf)


class MarkdownTests(unittest.TestCase):
    def test_output_name(self):
        self.assertEqual(pdf.output_path_for(Path("demo.notes.md")), Path("demo.notes.pdf"))
        self.assertEqual(pdf.output_path_for(Path("demo.md")), Path("demo.pdf"))

    def test_html_keeps_markdown_code_and_removes_active_tags(self):
        source = """# Demo

<script>alert(1)</script>

![remote](https://example.com/tracker.png)

```bash
echo hello
```

| A | B |
|---|---|
| 1 | 2 |
"""
        rendered = pdf.markdown_to_html(source, "Fallback")
        self.assertNotIn("<script", rendered.lower())
        self.assertNotIn("<img", rendered.lower())
        self.assertIn("Image omitted: remote", rendered)
        self.assertIn("<code", rendered)
        self.assertIn("echo hello", rendered)
        self.assertIn("<table>", rendered)

    def test_fallback_title_when_no_h1(self):
        rendered = pdf.markdown_to_html("A paragraph.", "Video title")
        self.assertIn("<h1>Video title</h1>", rendered)


class PdfIntegrationTests(unittest.TestCase):
    def test_unicode_and_code_remain_searchable(self):
        import fitz

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            markdown_path = root / "demo.notes.md"
            output_path = root / "demo.notes.pdf"
            markdown_path.write_text(
                """# Видео-конспект

Русский текст и English text.

## Команда

```python
print("привет")
```

| Время | Тема |
|---|---|
| 00:01 | Проверка |
""",
                encoding="utf-8",
            )
            result = pdf.render_pdf(markdown_path, output_path)
            self.assertEqual(result["pages"], 1)
            self.assertGreater(result["searchable_text_characters"], 30)
            self.assertTrue(output_path.is_file())
            with fitz.open(output_path) as document:
                text = "".join(page.get_text() for page in document)
                self.assertIn("Видео-конспект", text)
                self.assertIn('print("привет")', text)
                self.assertEqual(document.metadata.get("creator"), "video-to-notes")

    def test_existing_output_requires_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "notes.md"
            output = root / "notes.pdf"
            source.write_text("# Valid notes\n\nEnough searchable content.", encoding="utf-8")
            output.write_bytes(b"existing")
            with self.assertRaisesRegex(pdf.PdfRenderError, "--overwrite"):
                pdf.render_pdf(source, output)

    def test_empty_markdown_fails(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "empty.md"
            source.write_text("  \n", encoding="utf-8")
            with self.assertRaisesRegex(pdf.PdfRenderError, "empty"):
                pdf.render_pdf(source, root / "empty.pdf")


if __name__ == "__main__":
    unittest.main()
