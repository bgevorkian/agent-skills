from __future__ import annotations

import io
import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import urllib.error

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from yt import (  # noqa: E402
    build_api_url,
    format_http_error,
    jsonable,
    mutation_allowed,
    require_write_gate,
    resolve_custom_fields,
)


class FakeClient:
    def __init__(self) -> None:
        self.user_calls: list[str] = []

    def project_fields(self, project_selector: str):
        assert project_selector == "DEMO"
        return [
            {
                "id": "pcf-priority",
                "field": {"id": "f-priority", "name": "Priority", "localizedName": "Priority"},
                "bundle": {
                    "values": [
                        {"id": "enum-critical", "name": "Critical"},
                        {"id": "enum-normal", "name": "Normal"},
                    ]
                },
            },
            {
                "id": "pcf-assignee",
                "field": {"id": "f-assignee", "name": "Assignee", "localizedName": "Assignee"},
                "bundle": None,
            },
            {
                "id": "pcf-tags",
                "field": {"id": "f-tags", "name": "Tags", "localizedName": "Tags"},
                "bundle": {
                    "values": [
                        {"id": "tag-api", "name": "api"},
                        {"id": "tag-docs", "name": "docs"},
                    ]
                },
            },
        ]

    def resolve_user(self, selector: str):
        self.user_calls.append(selector)
        mapping = {
            "alice": {"id": "user-alice"},
            "bob": {"id": "user-bob"},
        }
        return mapping[selector]


def expect_rejected(fn, text: str) -> None:
    try:
        fn()
    except Exception:
        return
    raise AssertionError(text)


def test_url_builder() -> None:
    url = build_api_url(
        "https://youtrack.example.net",
        "issues",
        {"query": "project: DEMO #123", "$top": 5, "$skip": 10, "fields": "id,idReadable"},
    )
    assert url == (
        "https://youtrack.example.net/api/issues?"
        "query=project%3A+DEMO+%23123&%24top=5&%24skip=10&fields=id%2CidReadable"
    )


def test_jsonable() -> None:
    payload = {
        "decimal": Decimal("9.90"),
        "date": date(2026, 1, 2),
        "time": datetime(2026, 1, 2, tzinfo=timezone.utc),
        "bytes": b"\x00\xff",
    }
    assert jsonable(payload) == {
        "decimal": "9.90",
        "date": "2026-01-02",
        "time": "2026-01-02T00:00:00+00:00",
        "bytes": "00ff",
    }


def test_selectors() -> None:
    client = FakeClient()
    resolved = resolve_custom_fields(
        client,
        "DEMO",
        [
            {"name": "Priority", "$byName": "Critical"},
            {"name": "Assignee", "$user": "alice"},
            {"name": "Tags", "$byNames": ["api", "docs"]},
            {"name": "State", "value": {"name": "Open"}},
        ],
    )
    assert resolved == [
        {"name": "Priority", "value": {"id": "enum-critical"}},
        {"name": "Assignee", "value": {"id": "user-alice"}},
        {"name": "Tags", "value": [{"id": "tag-api"}, {"id": "tag-docs"}]},
        {"name": "State", "value": {"name": "Open"}},
    ]
    assert client.user_calls == ["alice"]


def test_mutation_gate() -> None:
    previous = os.environ.get("YOUTRACK_ALLOW_WRITE")
    try:
        os.environ.pop("YOUTRACK_ALLOW_WRITE", None)
        assert mutation_allowed(False) is False
        assert mutation_allowed(True) is False
        expect_rejected(lambda: require_write_gate(True), "write gate should reject without env")

        os.environ["YOUTRACK_ALLOW_WRITE"] = "true"
        assert mutation_allowed(False) is False
        assert mutation_allowed(True) is True
        expect_rejected(lambda: require_write_gate(False), "write gate should reject without flag")
        require_write_gate(True)
    finally:
        if previous is None:
            os.environ.pop("YOUTRACK_ALLOW_WRITE", None)
        else:
            os.environ["YOUTRACK_ALLOW_WRITE"] = previous


def test_http_error_formatting() -> None:
    error = urllib.error.HTTPError(
        "https://youtrack.example.net/api/issues",
        404,
        "Not Found",
        hdrs=None,
        fp=io.BytesIO(b'{"error":"issue not found"}'),
    )
    assert format_http_error(error) == "HTTP 404 Not Found: issue not found"


def main() -> None:
    test_url_builder()
    test_jsonable()
    test_selectors()
    test_mutation_gate()
    test_http_error_formatting()
    print("youtrack tests: OK")


if __name__ == "__main__":
    main()
