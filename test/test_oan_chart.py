"""Reject wrong, corrupt or unfinished central chart pins before any environment is touched."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("tested_oan_chart", ROOT / "ci/deploy/oan_chart.py")
chart = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chart)

BASE = "https://raw.githubusercontent.com/Centre-for-Open-Societal-Systems/oan-helm/"


def committed_pin():
    return json.loads((ROOT / "ci/deploy/oan-chart.json").read_text(encoding="utf-8"))["registry"]


class CentralChartTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "package.tgz"
        self.pin = {"repository": BASE + "a" * 40 + "/repository/",
                    "name": "openg2p-da-registry", "version": "1.0.0-dev.17", "platformVersion": "1.2.2-rc.614",
                    "promotionReady": True, "environment": "dev", "namespace": "da-registry", "release": "da-registry"}

    def package(self, *, child_version="1.2.2-rc.614", name=None, gate=False):
        info = {"name": name or self.pin["name"], "version": self.pin["version"], "appVersion": self.pin["platformVersion"],
                "dependencies": [{"name": "openg2p-registry", "alias": "registry",
                                  "repository": "https://openg2p.github.io/openg2p-helm", "version": self.pin["platformVersion"]}]}
        files = {"Chart.yaml": yaml.safe_dump(info),
                 "charts/openg2p-registry/Chart.yaml": yaml.safe_dump({"name": "openg2p-registry", "version": child_version})}
        if gate:
            files["templates/refactor-promotion-gate.yaml"] = '{{- fail "develop-refactor is incomplete: acceptance required" -}}'
        with tarfile.open(self.path, "w:gz") as archive:
            for member, body in files.items():
                payload = body.encode()
                item = tarfile.TarInfo(self.pin["name"] + "/" + member)
                item.size = len(payload)
                archive.addfile(item, io.BytesIO(payload))
        self.pin["sha256"] = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def test_valid_package_is_accepted(self):
        self.package()
        self.assertEqual(chart.verify(self.path, self.pin), self.pin)

    def test_changed_archive_is_rejected(self):
        self.package()
        self.path.write_bytes(self.path.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "checksum"):
            chart.verify(self.path, self.pin)

    def test_wrong_child_platform_is_rejected_even_when_checksum_matches(self):
        self.package(child_version="1.2.2-rc.544")
        with self.assertRaisesRegex(ValueError, "native platform"):
            chart.verify(self.path, self.pin)

    def test_wrong_registry_chart_is_rejected(self):
        self.package(name="openg2p-unrelated-registry")
        with self.assertRaisesRegex(ValueError, "name/version"):
            chart.verify(self.path, self.pin)

    def test_mutable_repository_ref_is_rejected(self):
        self.package()
        self.pin["repository"] = self.pin["repository"].replace("a" * 40, "main")
        with self.assertRaisesRegex(ValueError, "immutable"):
            chart.url(self.pin)

    def test_unready_pin_is_not_deployable(self):
        self.package()
        self.pin["promotionReady"] = False
        with self.assertRaisesRegex(ValueError, "Deployment blocked"):
            chart.require_deployable(self.pin, "dev")

    def test_ready_dev_pin_is_deployable_in_dev_only(self):
        self.package()
        self.assertTrue(chart.is_deployable(self.pin, "dev"))
        self.assertFalse(chart.is_deployable(self.pin, "staging"))
        with self.assertRaisesRegex(ValueError, "Deployment blocked"):
            chart.require_deployable(self.pin, "staging")

    def test_is_deployable_still_rejects_invalid_pin(self):
        self.package()
        self.pin["repository"] = self.pin["repository"].replace("a" * 40, "main")
        with self.assertRaisesRegex(ValueError, "immutable"):
            chart.is_deployable(self.pin, "dev")

    def test_placeholder_commit_is_rejected(self):
        self.package()
        self.pin["repository"] = self.pin["repository"].replace("a" * 40, "0" * 40)
        with self.assertRaisesRegex(ValueError, "placeholder"):
            chart.url(self.pin)

    def test_placeholder_checksum_is_rejected(self):
        self.package()
        self.pin["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "placeholder"):
            chart.validate_pin(self.pin)

    def test_values_url_must_name_the_chart_commit(self):
        self.package()
        self.pin["values"] = {"path": "environments/dev/values/da.yaml", "sha256": "b" * 64,
                              "url": BASE + "a" * 40 + "/environments/dev/values/da.yaml"}
        self.assertEqual(chart.validate_pin(self.pin), self.pin)
        self.pin["values"]["url"] = BASE + "c" * 40 + "/environments/dev/values/da.yaml"
        with self.assertRaisesRegex(ValueError, "pinned chart commit"):
            chart.validate_pin(self.pin)

    def test_verified_prefetched_archive_works_without_network(self):
        self.package()
        cache = Path(self.temp.name) / "cache"
        target = cache / self.pin["sha256"] / (self.pin["name"] + "-" + self.pin["version"] + ".tgz")
        target.parent.mkdir(parents=True)
        target.write_bytes(self.path.read_bytes())
        with patch.object(chart, "CENTRAL_CACHE", cache), \
                patch.object(chart.urllib.request, "urlopen", side_effect=AssertionError("Deploy node must remain offline")):
            result = chart.fetch(self.pin, Path(self.temp.name) / "deploy")
            self.assertEqual(result.read_bytes(), self.path.read_bytes())

    def test_corrupt_prefetched_archive_fails_without_network_fallback(self):
        self.package()
        cache = Path(self.temp.name) / "cache"
        target = cache / self.pin["sha256"] / (self.pin["name"] + "-" + self.pin["version"] + ".tgz")
        target.parent.mkdir(parents=True)
        target.write_bytes(b"corrupt")
        with patch.object(chart, "CENTRAL_CACHE", cache), \
                patch.object(chart.urllib.request, "urlopen", side_effect=AssertionError("No fallback")):
            with self.assertRaisesRegex(ValueError, "checksum"):
                chart.fetch(self.pin, Path(self.temp.name) / "deploy")

    def test_public_values_are_verified_and_read_from_cache(self):
        self.package()
        body = b"global:\n  registryHostname: example\n"
        self.pin["values"] = {"path": "environments/dev/values/da.yaml", "sha256": hashlib.sha256(body).hexdigest()}
        cache = Path(self.temp.name) / "cache"
        cached = cache / self.pin["values"]["sha256"] / "da.yaml"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(body)
        with patch.object(chart, "CENTRAL_CACHE", cache), \
                patch.object(chart.urllib.request, "urlopen", side_effect=AssertionError("offline")):
            out = chart.fetch_values(self.pin, Path(self.temp.name) / "out" / "values.yaml")
        self.assertEqual(out.read_bytes(), body)

    def test_changed_public_values_are_rejected(self):
        self.package()
        self.pin["values"] = {"path": "environments/dev/values/da.yaml", "sha256": hashlib.sha256(b"global: {}\n").hexdigest()}
        cache = Path(self.temp.name) / "cache"
        cached = cache / self.pin["values"]["sha256"] / "da.yaml"
        cached.parent.mkdir(parents=True)
        cached.write_bytes(b"global: {changed: true}\n")
        with patch.object(chart, "CENTRAL_CACHE", cache), \
                patch.object(chart.urllib.request, "urlopen", side_effect=AssertionError("offline")):
            with self.assertRaisesRegex(ValueError, "checksum"):
                chart.fetch_values(self.pin, Path(self.temp.name) / "out.yaml")

    def test_public_values_outside_the_dev_values_folder_are_rejected(self):
        self.package()
        self.pin["values"] = {"path": "../secrets.yaml", "sha256": "b" * 64}
        with self.assertRaisesRegex(ValueError, "path"):
            chart.fetch_values(self.pin, Path(self.temp.name) / "out.yaml")


class CommittedProfileTests(unittest.TestCase):
    def test_profile_targets_the_live_da_release(self):
        pin = committed_pin()
        self.assertEqual(pin["name"], "openg2p-da-registry")
        self.assertEqual(pin["version"], "1.0.0-dev.20")
        self.assertEqual((pin["release"], pin["namespace"], pin["environment"]), ("da-registry", "da-registry", "dev"))
        self.assertEqual(pin["values"]["path"], "environments/dev/values/da.yaml")

    def test_values_url_names_the_chart_commit(self):
        pin = committed_pin()
        self.assertEqual(pin["values"]["url"], pin["repository"][:-len("repository/")] + pin["values"]["path"])

    def test_platform_pin_matches_the_dockerfiles(self):
        platform = committed_pin()["platformVersion"]
        checked = 0
        for dockerfile in (ROOT / "docker").glob("*/Dockerfile"):
            text = dockerfile.read_text(encoding="utf-8")
            if "ARG RP_VERSION=" in text:
                checked += 1
                self.assertIn("ARG RP_VERSION=" + platform, text, dockerfile.as_posix())
        self.assertGreater(checked, 0)

    def test_platform_pin_matches_the_jenkinsfile(self):
        text = (ROOT / "Jenkinsfile").read_text(encoding="utf-8")
        self.assertIn('RP_VERSION     = "' + committed_pin()["platformVersion"] + '"', text)


if __name__ == "__main__":
    unittest.main()
