from pathlib import Path
import sys
import tempfile

import fitz

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from translate_pdf import extract_semantic_blocks  # noqa: E402


def main() -> None:
    with tempfile.TemporaryDirectory() as temp:
        root = Path(temp)
        pdf = root / "sample.pdf"
        document = fitz.open()
        for index in range(4):
            page = document.new_page(width=595, height=842)
            page.insert_text((72, 35), "Repeated Book Header", fontsize=9)
            page.insert_text((295, 820), str(index + 1), fontsize=9)
            if index == 0:
                page.insert_text((180, 120), "CHAPTER ONE", fontsize=19)
            body = (
                "This is a sufficiently long paragraph of source book text used to test semantic PDF extraction. "
                "It must remain in natural reading order while recurring headers and page numbers are removed."
            )
            page.insert_textbox(fitz.Rect(72, 160, 523, 400), body, fontsize=11)
        document.save(pdf)
        document.close()
        items, report = extract_semantic_blocks(pdf, root / "images")

    texts = [item["text"] for item in items if "text" in item]
    assert "Repeated Book Header" not in texts
    assert not any(text in {"1", "2", "3", "4"} for text in texts)
    assert any(item["type"] == "heading" and "CHAPTER ONE" in item["text"] for item in items)
    assert sum(item["type"] == "paragraph" for item in items) == 4
    assert report["pages"] == 4
    print("PDF semantic extraction test: OK")


if __name__ == "__main__":
    main()
