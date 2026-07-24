# EPUB translation workflow and lessons

## Architecture

1. Extract EPUB into an isolated work directory.
2. Read `META-INF/container.xml`, locate OPF, and enumerate XHTML/HTML manifest items.
3. Parse each document as XML.
4. Wrap only ordinary Latin-bearing text nodes in temporary `<t id="T0001">...</t>` markers.
5. Send the complete marked XHTML document to Pi in print/no-session mode.
6. Validate the returned marker set exactly, restore translated text into the original DOM, and checkpoint the document.
7. Update EPUB language metadata, validate Cyrillic coverage, pack EPUB, and print it through headless Chrome/Edge.
8. Validate PDF magic, size, and page count.

## Why whole-document translation

Translating isolated strings loses sentence context around italics, links, dialogue spans, and paragraph boundaries. The temporary marker approach lets the model see the whole chapter and its markup while the script retains deterministic ownership of the final DOM.

## Cross-chapter consistency

Each model call is independent. Use one shared glossary in every prompt. Include:

- recurring character and place names;
- franchise terminology and official Russian equivalents;
- invented technologies, ranks, factions, and forms of address;
- stylistic rules such as target reader age and dialogue punctuation.

The script stores source/target segment pairs in `translation-pairs/` under the work directory. Use them for a final terminology audit without rereading or modifying the source EPUB.

## Failure: every answer appeared to lose T0002

BeautifulSoup's `Doctype` is a subclass of `NavigableString`. Wrapping it produced this invalid shape:

```xml
<t id="T0001">html</t>
<html>...</html>
```

An XML parser accepts only the first root and therefore appeared to lose all later markers. The correct guard is:

```python
if type(node) is not NavigableString:
    continue
```

Do not use only `isinstance(node, NavigableString)`.

## Failure: `<t>` inside `<title>` disappeared

Parsing returned XHTML with `html.parser` treats `<title>` content as raw text, so temporary tags inside it are not discoverable. Parse returned XHTML with `features="xml"` after ensuring there is a single document root.

## Resume design

- A state file binds checkpoints to source hash, model, target language, style, and glossary hash.
- If those settings change, use `--restart`; silently reusing mixed checkpoints would create an inconsistent book.
- Each successful document gets a marker and source/target pair JSON.
- Failed model responses never overwrite the extracted document.

## Failure: front matter layout drifted and the cover split

Concatenating every EPUB stylesheet into one HTML document lets unrelated chapter/front-matter rules override each other. A cover scaled to the full A4 content width can also exceed the printable height and leave a thin fragment on the next page.

Render each spine XHTML separately with its own linked styles, inject only print-safe A4 rules, constrain image-only pages to the printable height, and merge the resulting PDFs. Visually inspect at least the first 12 pages after conversion.

## Failure: global widow/image fixes created more bad pages

Forcing `widows:3; orphans:3` on every paragraph and `page-break-before/after` on every `.full-page-images` block expanded a 103-page PDF to 120 pages and produced 27 image-only pages. Do not equate ordinary chapter-end white space with a defect.

Use the hybrid final pass instead:

1. `layout_qa.py` renders every page and flags measurable anomalies.
2. A full vision model distinguishes deliberate book design from true defects.
3. Apply only targeted fixes. `polish_pdf.py` centers pages that organically became image-only; it does not force illustrations onto new pages.
4. Rerun QA and visually inspect the reported pages.

## PDF limitations

- Embedded cover lettering stays in the source image.
- Some EPUBs intentionally contain both an outer and inner cover; decide whether a PDF should retain both.
- Fonts without Cyrillic glyphs may fall back to installed system fonts.
- CSS page geometry can differ from the reflowable EPUB; validate page count and inspect a few pages visually.
