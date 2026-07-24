from pathlib import Path
import sys
import tempfile

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from bs4 import BeautifulSoup  # noqa: E402
from translate_epub import clean_model_output, prepare_tagged_xhtml  # noqa: E402


def main() -> None:
    sample = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Cover</title></head>
<body><p>Hello <em>world</em>.</p><!-- keep --></body></html>"""
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "sample.xhtml"
        path.write_text(sample, encoding="utf-8")
        soup, records = prepare_tagged_xhtml(path)

    assert [value[1] for value in records.values()] == ["Cover", "Hello", "world"]
    tagged = str(soup)
    assert "<t id=\"T0001\">Cover</t>" in tagged
    assert "<t id=\"T0002\">Hello</t>" in tagged
    assert "<t id=\"T0003\">world</t>" in tagged
    assert "<t id=\"T0001\">html</t>" not in tagged

    returned = tagged.replace("Cover", "Обложка").replace("Hello", "Привет").replace("world", "мир")
    parsed = BeautifulSoup(clean_model_output(returned), "xml")
    found = {tag["id"]: tag.get_text() for tag in parsed.find_all("t")}
    assert found == {"T0001": "Обложка", "T0002": "Привет", "T0003": "мир"}
    print("markup regression test: OK")


if __name__ == "__main__":
    main()
