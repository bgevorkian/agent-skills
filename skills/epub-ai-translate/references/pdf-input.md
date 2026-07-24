# PDF input pipeline

## Supported PDFs

The pipeline supports born-digital PDFs with a usable text layer. It rebuilds a semantic, reflowable Russian book PDF rather than attempting pixel-identical text replacement.

Scanned/image-only PDFs are detected by text coverage. They require a separate OCR or page-vision extraction pass before translation. Do not silently treat OCR garbage as source prose.

## Extraction

PyMuPDF `Page.get_text("dict", sort=True)` supplies positioned blocks, lines, spans, font sizes, flags, and image blocks. `sort=True` provides a practical top-left to bottom-right order for ordinary single-column books.

The extractor:

1. estimates body size from character-weighted span sizes;
2. finds statistically recurring short blocks in the top/bottom page margins;
3. removes only repeated headers/footers and page-number patterns;
4. identifies headings by relative font size and `Chapter/Part/Book` labels;
5. retains meaningful images and their approximate reading position;
6. creates semantic translation chunks capped by character count and preferably split at headings.

Complex multi-column, footnote-heavy, mathematical, or magazine PDFs need a document-specific extraction review.

## Translation and reconstruction

Each chunk is represented as XML with stable `<t id="B...">` markers. A full model sees several pages at once plus the shared glossary. Marker sets are validated before checkpointing.

The translated content is rebuilt as HTML using traditional book typography and printed through Chrome/Edge. The output prioritizes reading quality over exact original pagination because Russian line length differs from English.

## Validation

After translation:

- verify all extracted block ids were translated;
- inspect source/output page counts as a diagnostic, not an equality requirement;
- run `layout_qa.py` over every page;
- have a full vision model inspect every contact sheet;
- apply only targeted corrections with `polish_pdf.py` or document-specific CSS;
- rerun until the vision verdict is `pass`.

## Known limitations

- Text embedded in images is not translated automatically.
- Forms, annotations, links, bookmarks, complex tables, equations, and exact typography may not survive semantic reflow.
- Multi-column reading order may require custom column detection.
- OCR quality determines scanned-PDF translation quality.
