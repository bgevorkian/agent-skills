from __future__ import annotations

import argparse
from pathlib import Path

import fitz


def polish(source: Path, output: Path, drop_pages: set[int]) -> dict[str, object]:
    source = source.resolve()
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    original = fitz.open(source)
    result = fitz.open()
    centered: list[int] = []
    dropped: list[int] = []

    for index, page in enumerate(original):
        page_number = index + 1
        if page_number in drop_pages:
            dropped.append(page_number)
            continue
        target = result.new_page(width=page.rect.width, height=page.rect.height)
        text = page.get_text().strip()
        images = page.get_image_info(xrefs=True)
        page_area = page.rect.width * page.rect.height
        image_area = sum(
            (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1])
            for item in images
        )
        image_ratio = image_area / page_area if page_area else 0.0
        should_center = len(text) < 30 and 0.03 <= image_ratio < 0.65 and bool(images)
        if should_center:
            top = min(item["bbox"][1] for item in images)
            bottom = max(item["bbox"][3] for item in images)
            content_height = bottom - top
            desired_top = (page.rect.height - content_height) / 2
            offset = desired_top - top
            target.show_pdf_page(
                fitz.Rect(0, offset, page.rect.width, page.rect.height + offset),
                original,
                index,
            )
            centered.append(page_number)
        else:
            target.show_pdf_page(target.rect, original, index)

    result.save(temporary, garbage=4, deflate=True)
    pages = len(result)
    original.close()
    result.close()
    temporary.replace(output)
    return {"output": str(output), "pages": pages, "centered_image_pages": centered, "dropped_pages": dropped}


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply deterministic fixes selected by the final vision layout QA")
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--drop-page", type=int, action="append", default=[])
    args = parser.parse_args()
    report = polish(args.input, args.output, set(args.drop_page))
    print(report)


if __name__ == "__main__":
    main()
