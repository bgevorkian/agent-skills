from __future__ import annotations

import argparse
import json
from pathlib import Path

import fitz
from PIL import Image, ImageDraw


def page_metrics(document: fitz.Document, index: int) -> dict[str, object]:
    page = document[index]
    page_area = page.rect.width * page.rect.height
    text = page.get_text().strip()
    blocks = [block for block in page.get_text("blocks") if block[4].strip()]
    images = page.get_image_info(xrefs=True)
    image_area = sum(
        max(0.0, (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1]))
        for item in images
    )
    image_ratio = image_area / page_area if page_area else 0.0
    text_top = min((block[1] for block in blocks), default=0.0) / page.rect.height
    text_bottom = max((block[3] for block in blocks), default=0.0) / page.rect.height
    image_top = min((item["bbox"][1] for item in images), default=0.0) / page.rect.height
    image_bottom = max((item["bbox"][3] for item in images), default=0.0) / page.rect.height
    next_text = document[index + 1].get_text().strip() if index + 1 < len(document) else ""
    next_is_chapter = next_text.upper().startswith("ГЛАВА ") or next_text.upper().startswith("CHAPTER ")

    flags: list[str] = []
    if len(text) < 10 and image_ratio < 0.01:
        flags.append("blank-page")
    if next_is_chapter and 0 < len(text) < 500 and image_ratio < 0.03:
        flags.append("sparse-tail-before-chapter")
    if len(text) < 30 and 0.03 <= image_ratio < 0.65:
        flags.append("image-only-page")
        if image_top < 0.25 and image_bottom < 0.60:
            flags.append("top-heavy-image")
    if blocks and text_bottom > 0.965:
        flags.append("text-near-bottom-edge")
    if any(item["bbox"][3] > page.rect.height * 0.98 for item in images):
        flags.append("image-near-bottom-edge")

    return {
        "page": index + 1,
        "characters": len(text),
        "text_lines": len(text.splitlines()),
        "image_ratio": round(image_ratio, 4),
        "text_band": [round(text_top, 3), round(text_bottom, 3)],
        "image_band": [round(image_top, 3), round(image_bottom, 3)],
        "next_is_chapter": next_is_chapter,
        "flags": flags,
    }


def render_sheets(document: fitz.Document, output_dir: Path, pages_per_sheet: int) -> list[str]:
    columns = 3
    rows = (pages_per_sheet + columns - 1) // columns
    sheets: list[str] = []
    for start in range(0, len(document), pages_per_sheet):
        thumbnails: list[Image.Image] = []
        for index in range(start, min(start + pages_per_sheet, len(document))):
            pixmap = document[index].get_pixmap(matrix=fitz.Matrix(0.42, 0.42), alpha=False)
            page_image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
            labelled = Image.new("RGB", (page_image.width, page_image.height + 26), "white")
            labelled.paste(page_image, (0, 26))
            ImageDraw.Draw(labelled).text((7, 6), f"Page {index + 1}", fill="black")
            thumbnails.append(labelled)
        cell_width = max(image.width for image in thumbnails)
        cell_height = max(image.height for image in thumbnails)
        sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (215, 215, 215))
        for offset, image in enumerate(thumbnails):
            sheet.paste(image, ((offset % columns) * cell_width, (offset // columns) * cell_height))
        path = output_dir / f"pages-{start + 1:04d}-{start + len(thumbnails):04d}.png"
        sheet.save(path)
        sheets.append(str(path))
    return sheets


def main() -> None:
    parser = argparse.ArgumentParser(description="Render PDF contact sheets and detect layout anomalies")
    parser.add_argument("pdf", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--pages-per-sheet", type=int, default=12)
    args = parser.parse_args()

    pdf = args.pdf.expanduser().resolve()
    output_dir = (args.output_dir or pdf.with_name(pdf.stem + "-layout-qa")).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    document = fitz.open(pdf)
    metrics = [page_metrics(document, index) for index in range(len(document))]
    sheets = render_sheets(document, output_dir, args.pages_per_sheet)
    report = {
        "pdf": str(pdf),
        "pages": len(document),
        "contact_sheets": sheets,
        "anomalies": [metric for metric in metrics if metric["flags"]],
    }
    report_path = output_dir / "layout-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(report_path), "pages": len(document), "sheets": len(sheets), "anomalies": len(report["anomalies"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
