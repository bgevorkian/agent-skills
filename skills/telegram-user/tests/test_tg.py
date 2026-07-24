from __future__ import annotations

import datetime as dt
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from telethon import types


MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "tg.py"
SPEC = importlib.util.spec_from_file_location("telegram_user_tg", MODULE_PATH)
assert SPEC and SPEC.loader
TG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = TG
SPEC.loader.exec_module(TG)


class TelegramUserTests(unittest.TestCase):
    def test_compute_default_session_file_posix(self) -> None:
        path = TG.compute_default_session_file(
            env={"XDG_DATA_HOME": "/tmp/data"},
            home=Path("/home/tester"),
            platform="posix",
        )
        self.assertEqual(path, Path("/tmp/data") / "telegram-user" / "telethon.session")

    def test_compute_default_session_file_windows(self) -> None:
        path = TG.compute_default_session_file(
            env={"APPDATA": r"D:\\AppData"},
            home=Path("C:/Users/tester"),
            platform="nt",
        )
        self.assertEqual(path, Path(r"D:\\AppData") / "telegram-user" / "telethon.session")

    def test_load_config_uses_env_and_override(self) -> None:
        config = TG.load_config(
            env={
                "TELEGRAM_API_ID": "12345",
                "TELEGRAM_API_HASH": "hash",
                "TELEGRAM_ALLOW_WRITE": "true",
            },
            session_override="~/tg/session.session",
            home=Path("/home/tester"),
            platform="posix",
        )
        self.assertEqual(config.api_id, 12345)
        self.assertEqual(config.api_hash, "hash")
        self.assertTrue(config.allow_write)
        self.assertEqual(config.session_file, Path("~/tg/session.session").expanduser())

    def test_to_jsonable_handles_common_types(self) -> None:
        data = {
            "when": dt.datetime(2024, 1, 2, 3, 4, 5),
            "blob": b"\x00\xff",
            "peer": types.InputPeerSelf(),
        }
        out = TG.to_jsonable(data)
        self.assertEqual(out["when"], "2024-01-02T03:04:05")
        self.assertEqual(out["blob"], {"_type": "bytes", "hex": "00ff"})
        self.assertEqual(out["peer"]["_"], "InputPeerSelf")

    def test_inflate_tl_builds_telethon_types(self) -> None:
        value = TG.inflate_tl({"_": "InputPeerUser", "user_id": 1, "access_hash": 2})
        self.assertIsInstance(value, types.InputPeerUser)
        self.assertEqual(value.user_id, 1)
        self.assertEqual(value.access_hash, 2)

    def test_raw_method_gate_heuristic(self) -> None:
        self.assertFalse(TG.raw_method_may_write("messages.GetDialogFiltersRequest"))
        self.assertFalse(TG.raw_method_may_write("contacts.SearchRequest"))
        self.assertTrue(TG.raw_method_may_write("messages.SendMessageRequest"))
        self.assertTrue(TG.raw_method_may_write("messages.ForwardMessagesRequest"))
        self.assertTrue(TG.raw_method_may_write("messages.ReadHistoryRequest"))

    def test_require_write_access_needs_both_switches(self) -> None:
        allowed = TG.Config(None, None, Path("x"), True, 1.0)
        denied = TG.Config(None, None, Path("x"), False, 1.0)
        TG.require_write_access(allowed, True, reason="send")
        with self.assertRaises(TG.CLIError):
            TG.require_write_access(allowed, False, reason="send")
        with self.assertRaises(TG.CLIError):
            TG.require_write_access(denied, True, reason="send")

    def test_parse_json_source_from_file_and_stdin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "payload.json"
            path.write_text('{"ok": true}', encoding="utf-8")
            self.assertEqual(TG.parse_json_source(f"@{path}"), {"ok": True})
        with mock.patch("sys.stdin", io.StringIO('{"n": 1}')):
            self.assertEqual(TG.parse_json_source("-"), {"n": 1})

    def test_parser_supports_nested_commands(self) -> None:
        parser = TG.build_parser()
        args = parser.parse_args(["saved", "messages", "--limit", "5"])
        self.assertEqual(args.command, "saved")
        self.assertEqual(args.saved_command, "messages")
        self.assertEqual(args.limit, 5)

        args = parser.parse_args([
            "--confirm-write",
            "folders",
            "add-peers",
            "work",
            "@a",
            "@b",
        ])
        self.assertEqual(args.command, "folders")
        self.assertEqual(args.folders_command, "add-peers")
        self.assertEqual(args.peers, ["@a", "@b"])
        self.assertTrue(args.confirm_write)

    def test_resolve_function_class(self) -> None:
        cls = TG.resolve_function_class("messages.GetDialogFiltersRequest")
        self.assertEqual(cls.__name__, "GetDialogFiltersRequest")


if __name__ == "__main__":
    unittest.main()
