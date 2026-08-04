from __future__ import annotations

import io
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import urllib.error

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))

from yt import (  # noqa: E402
    WRITE_COMMANDS,
    build_api_url,
    build_multipart,
    format_http_error,
    jsonable,
    mutation_allowed,
    parser,
    require_write_gate,
    resolve_custom_fields,
    run,
)


class FakeClient:
    def __init__(self) -> None:
        self.user_calls: list[str] = []

    def project_fields(self, project_selector: str):
        assert project_selector == "DEMO"
        return [
            {
                "id": "pcf-priority",
                "field": {
                    "id": "f-priority",
                    "name": "Priority",
                    "localizedName": "Priority",
                    "fieldType": {"id": "enum[1]"},
                },
                "bundle": {
                    "values": [
                        {"id": "enum-critical", "name": "Critical"},
                        {"id": "enum-normal", "name": "Normal"},
                    ]
                },
            },
            {
                "id": "pcf-assignee",
                "field": {
                    "id": "f-assignee",
                    "name": "Assignee",
                    "localizedName": "Assignee",
                    "fieldType": {"id": "user[1]"},
                },
                "bundle": None,
            },
            {
                "id": "pcf-tags",
                "field": {
                    "id": "f-tags",
                    "name": "Tags",
                    "localizedName": "Tags",
                    "fieldType": {"id": "enum[*]"},
                },
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


class RecordingClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object, object]] = []

    def get(self, path, params=None):
        self.calls.append(("GET", path, params, None))
        return {"ok": True}

    def post(self, path, body=None, params=None):
        self.calls.append(("POST", path, params, body))
        return {"ok": True}

    def request(self, method, path, params=None, body=None):
        self.calls.append((method, path, params, body))
        return None

    def upload(self, path, files, params=None):
        self.calls.append(("UPLOAD", path, params, files))
        return {"ok": True}


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
        {
            "name": "Priority",
            "$type": "SingleEnumIssueCustomField",
            "value": {"id": "enum-critical"},
        },
        {
            "name": "Assignee",
            "$type": "SingleUserIssueCustomField",
            "value": {"id": "user-alice"},
        },
        {
            "name": "Tags",
            "$type": "MultiEnumIssueCustomField",
            "value": [{"id": "tag-api"}, {"id": "tag-docs"}],
        },
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


def test_multipart_builder() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "example.txt"
        path.write_bytes(b"attachment-body")
        body, boundary = build_multipart([str(path)])
    assert boundary.encode("ascii") in body
    assert b'filename="example.txt"' in body
    assert b"Content-Type: text/plain" in body
    assert b"attachment-body" in body
    assert body.endswith(f"--{boundary}--\r\n".encode("ascii"))


def test_extended_command_surface_and_gates() -> None:
    expected_writes = {
        "create",
        "update",
        "comment",
        "comment-update",
        "comment-delete",
        "attach",
        "command",
        "article-create",
        "article-update",
        "article-attach",
    }
    assert WRITE_COMMANDS == expected_writes

    parse_cases = [
        ["attachments", "DEMO-1"],
        ["activities", "DEMO-1"],
        ["article-attachments", "DEMO-A-1"],
        ["--confirm-write", "comment-update", "DEMO-1", "comment-1", "--text", "x"],
        ["--confirm-write", "comment-delete", "DEMO-1", "comment-1"],
        ["--confirm-write", "attach", "DEMO-1", "file.txt"],
        ["--confirm-write", "command", "--query", "State Fixed", "--issues", "DEMO-1"],
        ["--confirm-write", "article-attach", "DEMO-A-1", "image.png"],
    ]
    for argv in parse_cases:
        parser().parse_args(argv)

    previous = os.environ.get("YOUTRACK_ALLOW_WRITE")
    try:
        os.environ.pop("YOUTRACK_ALLOW_WRITE", None)
        write_cases = [
            ["--confirm-write", "comment-update", "DEMO-1", "comment-1", "--text", "x"],
            ["--confirm-write", "comment-delete", "DEMO-1", "comment-1"],
            ["--confirm-write", "attach", "DEMO-1", "file.txt"],
            ["--confirm-write", "command", "--query", "State Fixed", "--issues", "DEMO-1"],
            ["--confirm-write", "article-attach", "DEMO-A-1", "image.png"],
        ]
        for argv in write_cases:
            expect_rejected(lambda argv=argv: run(parser().parse_args(argv)), "write should be gated")
    finally:
        if previous is None:
            os.environ.pop("YOUTRACK_ALLOW_WRITE", None)
        else:
            os.environ["YOUTRACK_ALLOW_WRITE"] = previous


def test_extended_operations_build_expected_requests() -> None:
    client = RecordingClient()
    run(parser().parse_args(["attachments", "DEMO-1", "--top", "5"]), client=client)
    assert client.calls[-1][:2] == ("GET", "issues/DEMO-1/attachments")
    assert client.calls[-1][2]["$top"] == 5

    run(parser().parse_args(["activities", "DEMO-1", "--skip", "2"]), client=client)
    assert client.calls[-1][:2] == ("GET", "issues/DEMO-1/activities")
    assert client.calls[-1][2]["$skip"] == 2

    run(parser().parse_args(["article-attachments", "DEMO-A-1"]), client=client)
    assert client.calls[-1][:2] == ("GET", "articles/DEMO-A-1/attachments")

    previous = os.environ.get("YOUTRACK_ALLOW_WRITE")
    try:
        os.environ["YOUTRACK_ALLOW_WRITE"] = "true"

        run(
            parser().parse_args(
                ["--confirm-write", "comment-update", "DEMO-1", "comment-1", "--text", "fixed"]
            ),
            client=client,
        )
        assert client.calls[-1] == (
            "POST",
            "issues/DEMO-1/comments/comment-1",
            {"fields": "id,text,created,updated,author(id,login,fullName)"},
            {"text": "fixed"},
        )

        run(
            parser().parse_args(
                ["--confirm-write", "comment-delete", "DEMO-1", "comment-1"]
            ),
            client=client,
        )
        assert client.calls[-1][:2] == (
            "DELETE",
            "issues/DEMO-1/comments/comment-1",
        )

        run(
            parser().parse_args(
                ["--confirm-write", "attach", "DEMO-1", "one.png", "two.txt"]
            ),
            client=client,
        )
        assert client.calls[-1][0:2] == ("UPLOAD", "issues/DEMO-1/attachments")
        assert client.calls[-1][3] == ["one.png", "two.txt"]

        run(
            parser().parse_args(
                [
                    "--confirm-write",
                    "command",
                    "--query",
                    "State Fixed",
                    "--issues",
                    "DEMO-1, DEMO-2",
                    "--comment",
                    "done",
                ]
            ),
            client=client,
        )
        command_body = client.calls[-1][3]
        assert command_body["issues"] == [
            {"idReadable": "DEMO-1"},
            {"idReadable": "DEMO-2"},
        ]
        assert command_body["comment"] == "done"

        run(
            parser().parse_args(
                ["--confirm-write", "article-attach", "DEMO-A-1", "image.png"]
            ),
            client=client,
        )
        assert client.calls[-1][0:2] == (
            "UPLOAD",
            "articles/DEMO-A-1/attachments",
        )
    finally:
        if previous is None:
            os.environ.pop("YOUTRACK_ALLOW_WRITE", None)
        else:
            os.environ["YOUTRACK_ALLOW_WRITE"] = previous


def main() -> None:
    test_url_builder()
    test_jsonable()
    test_selectors()
    test_mutation_gate()
    test_http_error_formatting()
    test_multipart_builder()
    test_extended_command_surface_and_gates()
    test_extended_operations_build_expected_requests()
    print("youtrack tests: OK")


if __name__ == "__main__":
    main()
