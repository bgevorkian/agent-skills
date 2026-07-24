from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] in {"-h", "--help"}:
        print("Usage: translate_book.py INPUT.(epub|pdf) [format-specific options]")
        print("EPUB options: translate_epub.py --help")
        print("PDF options:  translate_pdf.py --help")
        raise SystemExit(0 if len(sys.argv) >= 2 else 2)
    source = Path(sys.argv[1])
    scripts = Path(__file__).resolve().parent
    if source.suffix.lower() == ".epub":
        target = scripts / "translate_epub.py"
    elif source.suffix.lower() == ".pdf":
        target = scripts / "translate_pdf.py"
    else:
        raise SystemExit("Input must have .epub or .pdf extension")
    raise SystemExit(subprocess.run([sys.executable, str(target), *sys.argv[1:]]).returncode)


if __name__ == "__main__":
    main()
