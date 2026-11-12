"""The sample-approver password hook against a fake Keycloak, and its chart render."""
import importlib.util
import json
import os
import shutil
import subprocess
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
while not (ROOT / "helm").is_dir():
    ROOT = ROOT.parent
SCRIPT = next(ROOT.glob("helm/openg2p-*-registry/files/sample-approver-password.py"))
CHART = SCRIPT.parents[1]
spec = importlib.util.spec_from_file_location("sample_approver_password", SCRIPT)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


class FakeKeycloak(BaseHTTPRequestHandler):
    state = None

    def log_message(self, *_):
        pass

    def reply(self, code, body=None):
        raw = b"" if body is None else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def body(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            return dict(urllib.parse.parse_qsl(raw.decode()))
        return json.loads(raw) if raw else None

    def do_POST(self):
        s, form = self.state, self.body()
        realm = self.path.split("/")[2]
        if realm == "master":
            return self.reply(200, {"access_token": "admin"})
        user = s["users"].get(form["username"])
        if user and user["password"] == form["password"] and not user["requiredActions"]:
            return self.reply(200, {"access_token": "user"})
        return self.reply(401, {"error": "invalid_grant"})

    def do_GET(self):
        s = self.state
        s["lookups"] += 1
        name = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)["username"][0]
        if s["appearAfter"].get(name, 0) >= s["lookups"]:
            return self.reply(200, [])
        user = s["users"].get(name)
        self.reply(200, [] if not user else [{"id": name, "username": name, "requiredActions": user["requiredActions"]}])

    def do_PUT(self):
        s, body = self.state, self.body()
        user = s["users"][self.path.split("/")[5]]
        if self.path.endswith("/reset-password"):
            s["resets"].append((self.path.split("/")[5], body["temporary"]))
            user["password"] = body["value"]
        else:
            user["requiredActions"] = body["requiredActions"]
        self.reply(204)


class SampleApproverPasswordTest(unittest.TestCase):
    def setUp(self):
        FakeKeycloak.state = {"users": {}, "resets": [], "lookups": 0, "appearAfter": {}}
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeKeycloak)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.shutdown)
        self.env = {"KEYCLOAK_URL": f"http://127.0.0.1:{self.server.server_port}", "KEYCLOAK_USER": "admin",
                    "KEYCLOAK_PASSWORD": "x", "REALM": "staff", "USERS": '["alex.carter", "nina.patel"]',
                    "APPROVER_PASSWORD": "pass", "WAIT_SECONDS": "5", "DELAY_SECONDS": "0.01"}

    def run_hook(self, **env):
        with mock.patch.dict(os.environ, {**self.env, **env}, clear=False):
            return hook.main()

    def test_temporary_password_from_keycloak_init_becomes_permanent(self):
        users = FakeKeycloak.state["users"]
        users["alex.carter"] = {"password": "pass", "requiredActions": ["UPDATE_PASSWORD"]}
        users["nina.patel"] = {"password": "old", "requiredActions": []}
        self.assertEqual(self.run_hook(), 0)
        self.assertEqual(FakeKeycloak.state["resets"], [("alex.carter", False), ("nina.patel", False)])
        self.assertEqual(users["alex.carter"], {"password": "pass", "requiredActions": []})
        self.assertEqual(users["nina.patel"]["password"], "pass")

    def test_users_that_already_sign_in_are_left_alone(self):
        for name in ("alex.carter", "nina.patel"):
            FakeKeycloak.state["users"][name] = {"password": "pass", "requiredActions": []}
        self.assertEqual(self.run_hook(), 0)
        self.assertEqual(FakeKeycloak.state["resets"], [])

    def test_waits_for_keycloak_init_to_create_the_user(self):
        for name in ("alex.carter", "nina.patel"):
            FakeKeycloak.state["users"][name] = {"password": "pass", "requiredActions": ["UPDATE_PASSWORD"]}
        FakeKeycloak.state["appearAfter"] = {"alex.carter": 3}
        self.assertEqual(self.run_hook(), 0)
        self.assertEqual(sorted(FakeKeycloak.state["resets"]), [("alex.carter", False), ("nina.patel", False)])

    def test_missing_user_does_not_fail_the_release(self):
        self.assertEqual(self.run_hook(WAIT_SECONDS="0.05"), 0)
        self.assertEqual(FakeKeycloak.state["resets"], [])

    def test_empty_password_does_nothing(self):
        self.assertEqual(self.run_hook(APPROVER_PASSWORD=""), 0)
        self.assertEqual(FakeKeycloak.state["lookups"], 0)


@unittest.skipUnless(shutil.which(os.environ.get("HELM", "helm")), "helm not installed")
class SampleApproverPasswordRenderTest(unittest.TestCase):
    def render(self, *flags):
        helm = os.environ.get("HELM", "helm")
        out = subprocess.run([helm, "template", "r", str(CHART), "--show-only", "templates/sample-approver-password.yaml", *flags],
                             capture_output=True, text=True)
        return out.returncode, out.stdout + out.stderr

    def test_renders_the_hook_with_the_platform_password(self):
        if not (CHART / "charts").is_dir():
            self.skipTest("chart dependencies not built (helm dependency build)")
        code, out = self.render()
        self.assertEqual(code, 0, out)
        self.assertIn("kind: Job", out)
        self.assertIn('password: "pass"', out)
        self.assertIn('{ name: USERS, value: "[\\"alex.carter\\",\\"nina.patel\\"]" }', out)

    def test_empty_password_renders_nothing(self):
        if not (CHART / "charts").is_dir():
            self.skipTest("chart dependencies not built (helm dependency build)")
        code, out = self.render("--set", "registry.global.aweApproverUserPassword=")
        self.assertNotIn("kind: Job", out)


if __name__ == "__main__":
    unittest.main()
