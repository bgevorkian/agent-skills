from __future__ import annotations

import io
import importlib.util
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "pf.py"
SPEC = importlib.util.spec_from_file_location("prefect_ops_pf", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("failed to load pf.py")
pf = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pf)

DEPLOYMENT_ID = "00000000-0000-0000-0000-000000000001"
FLOW_RUN_ID = "00000000-0000-0000-0000-000000000002"


class FakeClient:
    def __init__(self, responder=None):
        self.responder = responder or (lambda method, path, body, allow_not_found: None)
        self.calls: list[dict[str, object]] = []

    def request(self, method, path, body=None, *, allow_not_found=False):
        self.calls.append(
            {
                "method": method,
                "path": path,
                "body": body,
                "allow_not_found": allow_not_found,
            }
        )
        return self.responder(method, path, body, allow_not_found)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            return self.payload
        return self.payload[:size]


class PrefectOpsTests(unittest.TestCase):
    def test_parse_params_supports_inline_json_and_file(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as handle:
            handle.write(json.dumps({"from_file": [1, 2]}))
            file_name = handle.name
        parser = pf.build_parser()
        args = parser.parse_args(
            [
                "run",
                "--deployment",
                DEPLOYMENT_ID,
                "--param",
                "count=2",
                "--param",
                'label="demo"',
                "--params",
                f"@{file_name}",
                "--confirm-write",
            ]
        )
        params = pf.parse_params(args)
        self.assertEqual(params, {"from_file": [1, 2], "count": 2, "label": "demo"})

    def test_resolve_deployment_by_uuid_and_name_variants(self):
        def responder(method, path, body, allow_not_found):
            if method == "GET" and path == f"/deployments/{DEPLOYMENT_ID}":
                return {"id": DEPLOYMENT_ID, "name": "demo"}
            if method == "GET" and path == "/deployments/name/flow%20x/deploy%20y":
                return {"id": DEPLOYMENT_ID, "name": "deploy y"}
            if method == "POST" and path == "/deployments/filter":
                return [{"id": DEPLOYMENT_ID, "name": "demo"}]
            raise AssertionError((method, path, body, allow_not_found))

        client = FakeClient(responder)
        self.assertEqual(pf.resolve_deployment(client, DEPLOYMENT_ID)["id"], DEPLOYMENT_ID)
        self.assertEqual(
            pf.resolve_deployment(client, "flow x/deploy y")["name"], "deploy y"
        )
        self.assertEqual(pf.resolve_deployment(client, "demo")["name"], "demo")

    def test_resolve_deployment_rejects_ambiguous_name(self):
        client = FakeClient(
            lambda method, path, body, allow_not_found: [
                {"id": DEPLOYMENT_ID},
                {"id": FLOW_RUN_ID},
            ]
        )
        with self.assertRaises(pf.CliError) as error:
            pf.resolve_deployment(client, "demo")
        self.assertIn("ambiguous", str(error.exception))

    def test_http_error_message_is_helpful_and_hides_api_key(self):
        def opener(request, timeout):
            raise urllib.error.HTTPError(
                request.full_url,
                403,
                "Forbidden",
                {},
                io.BytesIO(b'{"detail":"denied"}'),
            )

        client = pf.PrefectClient(
            api_url="https://prefect.example/api",
            api_key="super-secret-token",
            opener=opener,
        )
        with self.assertRaises(pf.CliError) as error:
            client.request("GET", "/admin/version")
        message = str(error.exception)
        self.assertIn("HTTP 403 GET /admin/version: denied", message)
        self.assertNotIn("super-secret-token", message)

    def test_mutations_require_both_gates(self):
        cases = [
            ["run", "--deployment", DEPLOYMENT_ID],
            ["cancel", "--id", FLOW_RUN_ID],
            ["retry", "--id", FLOW_RUN_ID],
            ["delete", "--id", FLOW_RUN_ID],
            ["pause", "--deployment", DEPLOYMENT_ID],
            ["resume", "--deployment", DEPLOYMENT_ID],
            ["set-state", "--id", FLOW_RUN_ID, "--type", "FAILED"],
            ["variable-set", "--name", "flag", "--value", "true"],
            ["variable-delete", "--name", "flag"],
        ]
        for base in cases:
            with self.subTest(case=base[0], missing="env"):
                client = FakeClient()
                with self.assertRaises(pf.CliError):
                    pf.execute(base + ["--confirm-write"], env={}, client=client)
                self.assertEqual(client.calls, [])
            with self.subTest(case=base[0], missing="confirm"):
                client = FakeClient()
                with self.assertRaises(pf.CliError):
                    pf.execute(base, env={pf.WRITE_ENV_NAME: pf.WRITE_ENV_VALUE}, client=client)
                self.assertEqual(client.calls, [])

    def test_mutations_execute_when_both_gates_are_present(self):
        def responder(method, path, body, allow_not_found):
            if method == "GET" and path == f"/deployments/{DEPLOYMENT_ID}":
                return {"id": DEPLOYMENT_ID, "name": "demo"}
            if method == "POST" and path == f"/deployments/{DEPLOYMENT_ID}/create_flow_run":
                return {"id": FLOW_RUN_ID, "name": "manual-run", "state": {"type": "SCHEDULED"}}
            if method == "POST" and path == f"/flow_runs/{FLOW_RUN_ID}/set_state":
                return {"status": "accepted", "state": body["state"]}
            if method == "DELETE" and path == f"/flow_runs/{FLOW_RUN_ID}":
                return None
            if method == "PATCH" and path == f"/deployments/{DEPLOYMENT_ID}":
                return {"ok": True}
            if method == "GET" and path == "/variables/name/flag":
                return {"name": "flag", "value": False}
            if method == "PATCH" and path == "/variables/name/flag":
                return {"name": "flag", "value": True}
            if method == "DELETE" and path == "/variables/name/flag":
                return None
            raise AssertionError((method, path, body, allow_not_found))

        env = {pf.WRITE_ENV_NAME: pf.WRITE_ENV_VALUE}
        run_client = FakeClient(responder)
        run_result = pf.execute(
            [
                "run",
                "--deployment",
                DEPLOYMENT_ID,
                "--param",
                "retries=2",
                "--confirm-write",
            ],
            env=env,
            client=run_client,
        )
        self.assertEqual(run_result["created_flow_run"], FLOW_RUN_ID)
        self.assertEqual(run_client.calls[1]["body"], {"parameters": {"retries": 2}})

        cancel_client = FakeClient(responder)
        pf.execute(
            ["cancel", "--id", FLOW_RUN_ID, "--force", "--confirm-write"],
            env=env,
            client=cancel_client,
        )
        self.assertEqual(cancel_client.calls[0]["body"]["state"]["type"], "CANCELLING")

        retry_client = FakeClient(responder)
        retry_result = pf.execute(
            ["retry", "--id", FLOW_RUN_ID, "--confirm-write"],
            env=env,
            client=retry_client,
        )
        self.assertEqual(retry_result["state"]["type"], "SCHEDULED")

        delete_client = FakeClient(responder)
        delete_result = pf.execute(
            ["delete", "--id", FLOW_RUN_ID, "--confirm-write"],
            env=env,
            client=delete_client,
        )
        self.assertEqual(delete_result, {"deleted_flow_run": FLOW_RUN_ID})

        pause_client = FakeClient(responder)
        pause_result = pf.execute(
            ["pause", "--deployment", DEPLOYMENT_ID, "--confirm-write"],
            env=env,
            client=pause_client,
        )
        self.assertTrue(pause_result["paused"])
        self.assertEqual(pause_client.calls[1]["body"], {"paused": True})

        resume_client = FakeClient(responder)
        resume_result = pf.execute(
            ["resume", "--deployment", DEPLOYMENT_ID, "--confirm-write"],
            env=env,
            client=resume_client,
        )
        self.assertFalse(resume_result["paused"])
        self.assertEqual(resume_client.calls[1]["body"], {"paused": False})

        set_state_client = FakeClient(responder)
        set_state_result = pf.execute(
            [
                "set-state",
                "--id",
                FLOW_RUN_ID,
                "--type",
                "completed",
                "--state-name",
                "Done",
                "--message",
                "ok",
                "--confirm-write",
            ],
            env=env,
            client=set_state_client,
        )
        self.assertEqual(set_state_result["state"]["type"], "COMPLETED")
        self.assertEqual(set_state_result["state"]["message"], "ok")

        variable_set_client = FakeClient(responder)
        variable_set_result = pf.execute(
            ["variable-set", "--name", "flag", "--value", "true", "--confirm-write"],
            env=env,
            client=variable_set_client,
        )
        self.assertEqual(variable_set_result["updated_variable"], "flag")
        self.assertEqual(variable_set_client.calls[1]["body"], {"value": True})

        variable_delete_client = FakeClient(responder)
        variable_delete_result = pf.execute(
            ["variable-delete", "--name", "flag", "--confirm-write"],
            env=env,
            client=variable_delete_client,
        )
        self.assertEqual(variable_delete_result, {"deleted_variable": "flag"})

    def test_variable_set_creates_when_missing(self):
        def responder(method, path, body, allow_not_found):
            if method == "GET" and path == "/variables/name/new_flag":
                self.assertTrue(allow_not_found)
                return None
            if method == "POST" and path == "/variables/":
                return {"name": body["name"], "value": body["value"]}
            raise AssertionError((method, path, body, allow_not_found))

        client = FakeClient(responder)
        result = pf.execute(
            ["variable-set", "--name", "new_flag", "--value", "1", "--confirm-write"],
            env={pf.WRITE_ENV_NAME: pf.WRITE_ENV_VALUE},
            client=client,
        )
        self.assertEqual(result, {"created_variable": "new_flag", "value": 1})

    def test_main_prints_json_error_for_missing_api_url(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        exit_code = pf.main(["server-version"], env={}, stdout=stdout, stderr=stderr)
        self.assertEqual(exit_code, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("missing Prefect API URL", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
