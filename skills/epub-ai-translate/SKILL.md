---
name: epub-ai-translate
description: Translate user-provided EPUB or PDF books into Russian with a full AI model, chapter/chunk context, a shared glossary, resumable checkpoints, preserved images, book-quality PDF output, and a final vision layout QA. Use when the user asks to translate an EPUB, PDF, e-book, or book into Russian or create a Russian PDF.
compatibility: Windows with uv, Pi CLI, Python 3.13, and Chrome or Edge. PDF input requires a usable text layer; scanned PDFs require OCR/vision extraction first.
---

# EPUB/PDF AI Translate

Переводит предоставленные пользователем EPUB **или PDF** на русский через полноценную AI-модель. Поддерживает общий глоссарий, контекстные XHTML/semantic chunks, checkpoints/resume, иллюстрации, книжную перевёрстку и финальный vision layout-QA.

## Единый запуск

Из каталога skill:

```bat
cd /d %USERPROFILE%\.pi\agent\skills\epub-ai-translate
uv run --python 3.13 --with beautifulsoup4 --with lxml --with pypdf --with pymupdf python scripts\translate_book.py "C:\path\book.epub-or-pdf" --model openai-codex/gpt-5.4 --workers 3 --glossary "C:\path\glossary.txt"
```

Unix:

```bash
cd ~/.pi/agent/skills/epub-ai-translate
uv run --python 3.13 --with beautifulsoup4 --with lxml --with pypdf --with pymupdf python scripts/translate_book.py "/path/book.epub-or-pdf" --model openai-codex/gpt-5.4 --workers 3 --glossary "/path/glossary.txt"
```

Dispatcher выбирает pipeline по расширению:

- EPUB input → отдельные русские EPUB + PDF, исходные XHTML/CSS/изображения сохраняются.
- PDF input с text layer → semantic extraction, удаление повторных headers/footers/page numbers, перевод контекстными chunks, reflow в новый русский PDF.
- Scanned/image-only PDF → остановка без повреждений; сначала нужен OCR/vision extraction.

Format-specific help:

```bat
python scripts\translate_epub.py --help
python scripts\translate_pdf.py --help
```

Python всегда запускать через `uv run --python 3.13`, не напрямую.

## Основные параметры

- `--output-pdf PATH`, для EPUB также `--output-epub PATH`.
- `--workers N` — безопасный default `3`.
- `--model PROVIDER/MODEL` — default `openai-codex/gpt-5.4`; не переходить на mini, если качество важнее скорости.
- `--glossary PATH` — общий UTF-8 словарь имён и терминов.
- `--style TEXT` — возраст, жанр, тон и стилистические правила.
- `--work-dir PATH` — каталог checkpoints.
- `--restart` — удалить checkpoints и начать заново.
- `--force` — разрешить перезапись output.
- EPUB only: `--epub-only`.

## Обязательный workflow

1. Проверить input (`.epub`/`.pdf`) и целевой формат. По умолчанию — русский PDF; для EPUB также сохранить русский EPUB.
2. Для PDF проверить text layer. Если pipeline сообщает об отсутствии надёжного текста, не имитировать перевод: согласовать OCR/vision pass.
3. Подготовить glossary с каноническими именами, местами, фракциями, техникой и официальной терминологией франшизы.
4. Для художественной книги использовать полную модель и `--style`, соответствующий возрасту, жанру и тону.
5. Запускать как длительную фоновую задачу: pipeline порождает Pi agents, поэтому `bg_run` должен иметь `isAgent: true`.
6. Следить за `bg_status`/`bg_logs`; повторный запуск с тем же work-dir продолжает по checkpoints.
7. Проверить translation pairs/checkpoint JSON и межглавную согласованность имён/терминов.
8. Обязательно выполнить layout-QA:
   ```bat
   uv run --python 3.13 --with pymupdf --with pillow python scripts\layout_qa.py "C:\path\translated.pdf"
   ```
   Передать `layout-report.json` и **все** contact sheets отдельной полной vision-модели по [layout-qa prompt](references/layout-qa-prompt.md). Долгий Pi-review запускать через `bg_run`, `isAgent: true`.
9. Для точечных исправлений:
   ```bat
   uv run --python 3.13 --with pymupdf python scripts\polish_pdf.py input.pdf output.pdf [--drop-page N]
   ```
   Скрипт центрирует только страницы, уже ставшие image-only. Не выносить все картинки на отдельные страницы глобальным CSS.
10. Повторять vision-QA до `pass`: 0 severe, 0 moderate либо moderate явно приняты как намеренная книжная композиция.
11. Проверить PDF magic/размер/число страниц, долю кириллицы и визуально первые + аномальные страницы. Затем сообщить полные пути.

## Правила качества

- Литературный AI-перевод, не посегментный машинный перевод.
- EPUB переводится целыми XHTML-разделами; PDF — semantic chunks с несколькими страницами и общей терминологией.
- Не суммировать, не сокращать, не цензурировать и не добавлять текст.
- Сохранять диалоги, регистр, эмоциональные оттенки, звукоподражания и авторский темп.
- Не переводить ISBN, URL и товарные знаки вне обычной прозы.
- Не менять source-файл; output всегда отдельный.
- Нормальный пробел в конце главы допустим; глава начинается с новой страницы.
- Текст внутри изображений/обложки не переводится без отдельного OCR/image-editing этапа.

## EPUB technical rules

- XHTML парсить как XML; не считать `Doctype`, declaration, comments или CDATA переводимым `NavigableString`.
- Модель переводит только временные `<t id="...">`; каждый id должен вернуться ровно один раз.
- `mimetype` при упаковке EPUB должен идти первым без сжатия.
- Каждый spine-XHTML печатать отдельно и затем объединять PDF: глобальное объединение CSS вызывает конфликты.
- Ограничивать image-only cover областью A4, чтобы она не разрывалась.

## PDF input rules

- Использовать PyMuPDF `Page.get_text("dict", sort=True)` и координаты blocks/spans для reading order и семантики.
- Удалять только статистически повторяющиеся marginal headers/footers и page numbers; не удалять редкий авторский текст.
- Heading определять по размеру/жирности и словам `Chapter/Part/Book`; обычный body reflow в `<p>`.
- Изображения сохранять по позиции чтения; мелкие повторные декорации можно дедуплицировать.
- PDF reflow не обещает пиксельное совпадение с исходником: русский текст имеет другую длину, поэтому приоритет — читаемая книжная композиция.
- Частичный model response никогда не принимать: retry до трёх раз, затем fail без перезаписи source.

## Lessons learned

- Не навязывать `page-break` всем иллюстрациям и не повышать глобально `widows/orphans`: это создаёт лишние страницы.
- Vision-QA должен отличать намеренный chapter-end whitespace от ошибки.
- Windows CMD портит Unicode paths; для путей с кириллицей передавать их через Python wrapper, а не CMD arguments.

Подробнее: [workflow](references/workflow.md), [PDF input](references/pdf-input.md), [vision QA](references/layout-qa-prompt.md).
