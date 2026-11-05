"""Rollback behaviour of ci/deploy-dev.sh and the pin updater, with stand-in helm/kubectl.

No network, no cluster. Standard library only (runs on the Jenkins agent's stock Python).
    python3 -m unittest discover -s test -p test_deploy_ci.py -v
"""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

HELM = r'''#!/usr/bin/env bash
echo "helm $*" >> "$LOG"
case "$1" in
  status)   printf '{"info":{"status":"%s"},"version":9}\\n' "${RELEASE_STATUS:-deployed}" ;;
  template) echo "kind: ConfigMap" ;;
  get)      echo "registry: {}" ;;
  history)  case " $* " in *" json "*) echo "${HISTORY_JSON}" ;; *) echo "REVISION STATUS" ;; esac ;;
  upgrade)  exit "${UPGRADE_RC:-0}" ;;
  rollback) exit "${ROLLBACK_RC:-0}" ;;
esac
exit 0
'''

KUBECTL = r'''#!/usr/bin/env bash
echo "kubectl $*" >> "$LOG"
if [ "$1" = rollout ]; then exit "${ROLLOUT_RC:-0}"; fi
exit 0
'''

# Stands in for ci/deploy/oan_chart.py (which would download the pinned chart).
CHART_STUB = r'''import sys
a = sys.argv[1:]
if a[0] == "fetch":
    import os
    os.makedirs(a[2], exist_ok=True)
    p = os.path.join(a[2], "chart.tgz"); open(p, "w").write("x"); print(p)
elif a[0] == "values":
    open(a[2], "w").write("registry: {}\n"); print(a[2])
elif a[0] in ("release", "namespace"):
    print("da-registry")
elif a[0] in ("version", "platform"):
    print("1.0.0-test")
'''

DEPLOYED = json.dumps([{"revision": 2, "status": "superseded"}, {"revision": 3, "status": "deployed"},
                       {"revision": 4, "status": "failed"}])


class DeployRollbackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        base = Path(self.tmp.name)
        self.repo = base / "repo"
        (self.repo / "ci/deploy").mkdir(parents=True)
        shutil.copy(ROOT / "ci/deploy-dev.sh", self.repo / "ci/deploy-dev.sh")
        (self.repo / "ci/deploy/oan_chart.py").write_text(CHART_STUB)
        self.bin = base / "bin"
        self.bin.mkdir()
        for name, body in (("helm", HELM), ("kubectl", KUBECTL)):
            path = self.bin / name
            path.write_text(body)
            path.chmod(path.stat().st_mode | stat.S_IXUSR)
        self.log = base / "calls.log"
        self.log.write_text("")

    def run_deploy(self, **env):
        e = dict(os.environ, PATH=str(self.bin) + os.pathsep + os.environ["PATH"], LOG=str(self.log),
                 KUBECONFIG="/nonexistent", AWS_ACCOUNT_ID="123456789012", BUILD_NUMBER="7",
                 HISTORY_JSON=DEPLOYED)
        e.update(env)
        done = subprocess.run(["bash", str(self.repo / "ci/deploy-dev.sh"), "abcdef123456"], cwd=str(self.repo),
                              env=e, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)
        return done.returncode, done.stdout, self.log.read_text()

    def test_success_does_not_roll_back(self):
        rc, out, calls = self.run_deploy()
        self.assertEqual(rc, 0, out)
        self.assertNotIn("helm rollback", calls)
        self.assertIn("helm upgrade da-registry", calls)
        self.assertIn("--reset-values", calls)
        self.assertNotIn("--atomic", calls)

    def test_failed_upgrade_rolls_back_to_last_deployed_revision(self):
        rc, out, calls = self.run_deploy(UPGRADE_RC="1")
        self.assertNotEqual(rc, 0)
        self.assertIn("helm rollback da-registry 3 -n da-registry", calls)   # 3 = last `deployed`, not the failed 4
        self.assertTrue((self.repo / "deploy-failure-7.txt").exists())
        self.assertIn("== failure: helm upgrade did not complete", (self.repo / "deploy-failure-7.txt").read_text())

    def test_failed_rollout_rolls_back(self):
        rc, out, calls = self.run_deploy(ROLLOUT_RC="1")
        self.assertNotEqual(rc, 0)
        self.assertIn("helm rollback da-registry 3 -n da-registry", calls)
        self.assertIn("did not roll out", (self.repo / "deploy-failure-7.txt").read_text())

    def test_diagnostics_are_saved_before_the_rollback(self):
        rc, out, calls = self.run_deploy(UPGRADE_RC="1")
        lines = calls.splitlines()
        rollback = next(i for i, l in enumerate(lines) if l.startswith("helm rollback"))
        events = next(i for i, l in enumerate(lines) if l.startswith("kubectl get events"))
        self.assertLess(events, rollback)

    def test_failure_without_a_deployed_revision_does_not_roll_back(self):
        rc, out, calls = self.run_deploy(UPGRADE_RC="1", HISTORY_JSON=json.dumps([{"revision": 1, "status": "failed"}]))
        self.assertNotEqual(rc, 0)
        self.assertNotIn("helm rollback", calls)
        self.assertIn("no earlier deployed revision", out)

    def test_a_failed_rollback_still_fails_the_build(self):
        rc, out, calls = self.run_deploy(UPGRADE_RC="1", ROLLBACK_RC="1")
        self.assertNotEqual(rc, 0)
        self.assertIn("ROLLBACK FAILED", out)

    def test_interrupted_release_is_refused_before_any_change(self):
        rc, out, calls = self.run_deploy(RELEASE_STATUS="pending-upgrade")
        self.assertNotEqual(rc, 0)
        self.assertNotIn("helm upgrade", calls)
        self.assertNotIn("helm rollback", calls)


def load_bump():
    spec = importlib.util.spec_from_file_location("bump_pin_under_test", ROOT / "ci/deploy/bump_pin.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def fake_archive(version="1.0.0-dev.21", app="1.2.2-rc.700"):
    body = "apiVersion: v2\nname: openg2p-da-registry\nversion: %s\nappVersion: %s\n" % (version, app)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        data = body.encode()
        info = tarfile.TarInfo("openg2p-da-registry/Chart.yaml")
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class BumpPinTests(unittest.TestCase):
    COMMIT = "b" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bump = load_bump()
        profile = Path(self.tmp.name) / "oan-chart.json"
        shutil.copy(ROOT / "ci/deploy/oan-chart.json", profile)
        self.bump.PROFILE = profile
        self.archive = fake_archive()
        self.digest = hashlib.sha256(self.archive).hexdigest()
        self.files = {
            "releases/current.yaml": b"charts:\n  openg2p-da-registry: 1.0.0-dev.21\n  openg2p-farmer-registry: 1.0.0-dev.20\n",
            "repository/openg2p-da-registry-1.0.0-dev.21.tgz": self.archive,
            "repository/SHA256SUMS": ("%s  openg2p-da-registry-1.0.0-dev.21.tgz\n" % self.digest).encode(),
            "environments/dev/values/da.yaml": b"registry: {}\n",
        }

    def fetch(self, uri):
        path = uri.split("/oan-helm/" + self.COMMIT + "/")[1]
        return self.files[path]

    def test_pin_is_rebuilt_from_the_commit(self):
        profiles = self.bump.new_pin(self.COMMIT, fetch=self.fetch)
        pin = profiles["registry"]
        self.assertEqual(pin["version"], "1.0.0-dev.21")          # taken from releases/current.yaml
        self.assertEqual(pin["sha256"], self.digest)
        self.assertEqual(pin["platformVersion"], "1.2.2-rc.700")  # read from the archive
        self.assertTrue(pin["repository"].endswith("/oan-helm/" + self.COMMIT + "/repository/"))
        self.assertEqual(pin["values"]["url"], pin["repository"][:-len("repository/")] + pin["values"]["path"])
        self.assertEqual(pin["values"]["sha256"], hashlib.sha256(b"registry: {}\n").hexdigest())
        self.assertEqual(pin["namespace"], "da-registry")         # untouched fields stay

    def test_archive_not_matching_sha256sums_is_rejected(self):
        self.files["repository/SHA256SUMS"] = ("%s  openg2p-da-registry-1.0.0-dev.21.tgz\n" % ("0" * 64)).encode()
        with self.assertRaisesRegex(ValueError, "SHA256SUMS"):
            self.bump.new_pin(self.COMMIT, fetch=self.fetch)

    def test_version_missing_from_sha256sums_is_rejected(self):
        self.files["repository/SHA256SUMS"] = b""
        with self.assertRaisesRegex(ValueError, "not listed"):
            self.bump.new_pin(self.COMMIT, fetch=self.fetch)

    def test_archive_with_another_chart_version_is_rejected(self):
        self.files["repository/openg2p-da-registry-1.0.0-dev.21.tgz"] = fake_archive(version="1.0.0-dev.20")
        self.files["repository/SHA256SUMS"] = ("%s  openg2p-da-registry-1.0.0-dev.21.tgz\n" % hashlib.sha256(
            self.files["repository/openg2p-da-registry-1.0.0-dev.21.tgz"]).hexdigest()).encode()
        with self.assertRaisesRegex(ValueError, "expected 1.0.0-dev.21"):
            self.bump.new_pin(self.COMMIT, fetch=self.fetch)

    def test_branch_or_short_commit_is_rejected(self):
        for bad in ("main", "abc1234", "B" * 40):
            with self.assertRaises(ValueError):
                self.bump.new_pin(bad, fetch=self.fetch)

    def test_placeholder_version_is_rejected(self):
        with self.assertRaises(ValueError):
            self.bump.new_pin(self.COMMIT, version="0.0.0-develop.1", fetch=self.fetch)


class ProposePinTests(unittest.TestCase):
    """--latest: what the scheduled workflow uses to decide whether to open a pin pull request."""
    HEAD = "c" * 40

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bump = load_bump()
        self.root = Path(self.tmp.name)
        (self.root / "ci/deploy").mkdir(parents=True)
        (self.root / "ci/pipelines").mkdir(parents=True)
        (self.root / "test").mkdir()
        (self.root / "docker/staff-api").mkdir(parents=True)
        (self.root / "docker/local-dev/data-loaders").mkdir(parents=True)
        shutil.copy(ROOT / "ci/deploy/oan-chart.json", self.root / "ci/deploy/oan-chart.json")
        shutil.copy(ROOT / "test/test_oan_chart.py", self.root / "test/test_oan_chart.py")
        shutil.copy(ROOT / "ci/pipelines/dev.groovy", self.root / "ci/pipelines/dev.groovy")
        for name in ("docker/staff-api/Dockerfile", "docker/local-dev/data-loaders/Dockerfile"):
            shutil.copy(ROOT / "docker/staff-api/Dockerfile", self.root / name)
        self.bump.PROFILE = self.root / "ci/deploy/oan-chart.json"
        self.bump.ROOT = self.root
        self.old = json.loads(self.bump.PROFILE.read_text(encoding="utf-8"))
        self.pinned = self.old["registry"]
        self.files = {}

    def publish(self, version, app, values=b"registry: {}\n"):
        archive = fake_archive(version=version, app=app)
        name = "openg2p-da-registry-%s.tgz" % version
        self.files = {
            "releases/current.yaml": ("charts:\n  openg2p-da-registry: %s\n" % version).encode(),
            "repository/" + name: archive,
            "repository/SHA256SUMS": ("%s  %s\n" % (hashlib.sha256(archive).hexdigest(), name)).encode(),
            "environments/dev/values/da.yaml": values,
        }
        return hashlib.sha256(archive).hexdigest()

    def fetch(self, uri):
        return self.files[uri.split("/oan-helm/" + self.HEAD + "/")[1]]

    def propose(self):
        return self.bump.proposal(self.old, fetch=self.fetch, head=lambda: self.HEAD)

    def test_version_order(self):
        key = self.bump.version_key
        self.assertLess(key("1.0.0-dev.9"), key("1.0.0-dev.10"))     # numeric, not text order
        self.assertLess(key("1.0.0-dev.20"), key("1.0.0-dev.21"))
        self.assertLess(key("1.0.0-dev.99"), key("1.0.0"))
        with self.assertRaises(ValueError):
            key("latest")

    def test_newer_chart_is_proposed(self):
        self.publish("1.0.0-dev.21", "1.2.2-rc.700")
        new, why = self.propose()
        self.assertIsNotNone(new)
        self.assertIn("newer chart 1.0.0-dev.21", why)
        self.assertTrue(new["registry"]["repository"].endswith("/oan-helm/" + self.HEAD + "/repository/"))

    def test_same_chart_and_values_is_up_to_date(self):
        digest = self.publish(self.pinned["version"], self.pinned["platformVersion"])
        self.pinned["sha256"] = digest                      # as if the archive were the pinned one
        self.pinned["values"]["sha256"] = hashlib.sha256(self.files["environments/dev/values/da.yaml"]).hexdigest()
        new, why = self.propose()
        self.assertIsNone(new)
        self.assertIn("up to date", why)

    def test_values_only_change_is_proposed_with_the_same_chart(self):
        digest = self.publish(self.pinned["version"], self.pinned["platformVersion"], values=b"registry: {changed: true}\n")
        self.pinned["sha256"] = digest
        new, why = self.propose()
        self.assertIsNotNone(new)
        self.assertIn("public values changed", why)
        self.assertEqual(new["registry"]["version"], self.pinned["version"])

    def test_older_chart_is_never_proposed(self):
        self.publish("1.0.0-dev.19", "1.2.2-rc.600")
        with self.assertRaisesRegex(ValueError, "downgrade"):
            self.propose()

    def test_changed_archive_for_the_same_version_is_refused(self):
        self.publish(self.pinned["version"], "1.2.2-rc.999")  # different bytes, same version
        with self.assertRaisesRegex(ValueError, "immutable"):
            self.propose()

    def test_head_commit_is_read_with_git_ls_remote(self):
        out = "%s\trefs/heads/main\n" % self.HEAD
        self.assertEqual(self.bump.head_commit(run=lambda cmd: out), self.HEAD)
        with self.assertRaises(ValueError):
            self.bump.head_commit(run=lambda cmd: "")

    def test_files_that_must_agree_are_updated_with_the_pin(self):
        self.publish("1.0.0-dev.21", "1.2.2-rc.700")
        new, _ = self.propose()
        changed = self.bump.update_companions(self.pinned, new["registry"], root=self.root)
        text = lambda rel: (self.root / rel).read_text(encoding="utf-8")
        self.assertIn('RP_VERSION     = "1.2.2-rc.700"', text("ci/pipelines/dev.groovy"))
        self.assertIn('self.assertEqual(pin["version"], "1.0.0-dev.21")', text("test/test_oan_chart.py"))
        self.assertIn("ARG RP_VERSION=1.2.2-rc.700", text("docker/staff-api/Dockerfile"))
        self.assertIn("ARG RP_VERSION=1.2.2-rc.700", text("docker/local-dev/data-loaders/Dockerfile"))
        self.assertEqual(sorted(changed), sorted(["ci/pipelines/dev.groovy", "test/test_oan_chart.py", "docker/staff-api/Dockerfile",
                                                  "docker/local-dev/data-loaders/Dockerfile"]))

    def test_values_only_change_leaves_platform_files_alone(self):
        digest = self.publish(self.pinned["version"], self.pinned["platformVersion"], values=b"registry: {x: 1}\n")
        self.pinned["sha256"] = digest
        new, _ = self.propose()
        self.assertEqual(self.bump.update_companions(self.pinned, new["registry"], root=self.root), [])


class PipelineWiringTests(unittest.TestCase):
    """Jenkinsfile: build (digests) -> package chart -> deploy with rollback -> publish that chart, last."""

    def setUp(self):
        self.text = (ROOT / "ci/pipelines/dev.groovy").read_text()

    def stage(self, name, following):
        return self.text.split("stage('%s')" % name, 1)[1].split(following, 1)[0]

    def test_publishing_is_the_last_stage_and_follows_the_deploy(self):
        order = [self.text.index("stage('%s')" % n) for n in
                 ("Build & Push", "Package chart", "Deploy to Development", "Publish chart")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(self.text.count("stage('"), 8)
        self.assertLess(self.text.index("stage('Publish chart')"), self.text.index("\n        post {"))

    def test_the_deploy_installs_the_packaged_chart_and_still_fails_the_build(self):
        stage = self.stage("Deploy to Development", "stage('Publish chart')")
        self.assertIn('BUILT_CHART_DIR="$PWD/built-chart" bash ci/deploy-dev.sh', stage)
        self.assertNotIn("catchError(", stage)

    def test_digests_are_captured_from_the_push_output_for_every_component(self):
        build = self.stage("Build & Push", "stage('Package chart')")
        self.assertIn(".build/image-digests.tsv", build)
        self.assertLess(build.index("docker push ${image}"), build.index("image-digests.tsv\n"))
        self.assertIn("grep -oE 'digest: sha256:[0-9a-f]{64}'", build)
        self.assertNotIn("aws ecr describe-images", self.text)          # no extra AWS permission is needed
        self.assertNotIn("\\{", build)                                    # an invalid Groovy escape

    def test_the_publish_stage_cannot_fail_the_build(self):
        stage = self.stage("Publish chart", "\n        post {")
        self.assertIn("catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE')", stage)
        self.assertIn("bash ci/deploy/publish-chart.sh", stage)
        self.assertIn("when { branch 'develop' }", stage)
        self.assertIn("OAN_HELM_FORK_CRED_ID", stage)
        for absent in ("KUBECONFIG", "helm upgrade", "kubectl", "docker "):
            self.assertNotIn(absent, stage)
        self.assertIn('OAN_HELM_FORK_CRED_ID = "oan-helm-fork-token"', self.text)

    def test_the_pull_request_stages_are_gone(self):
        self.assertNotIn("Open oan-helm image PR", self.text)
        self.assertNotIn("Propose chart pin update", self.text)

    def test_every_component_the_pipeline_builds_has_a_chart_image(self):
        self.assertIn('ECR_BASE       = "openg2p/da-registry"', self.text)
        package = (ROOT / "ci/deploy/package-chart.sh").read_text()
        deploy = (ROOT / "ci/deploy-dev.sh").read_text()
        for component in ("staff-api", "staff-ui", "partner-api", "celery", "db-seed"):
            self.assertIn("name: '%s'," % component, self.text)
            self.assertIn("    %s) paths=" % component, package)
            self.assertIn("{repository: '${IMAGE_REPOSITORY}/%s', tag: '${TAG}'}" % component, deploy)

    def test_the_chart_has_no_fixed_version(self):
        chart = (ROOT / "helm/openg2p-da-registry/Chart.yaml").read_text(encoding="utf-8")
        self.assertIn("version: 0.0.0\n", chart)

    def test_braces_balance(self):
        self.assertEqual(self.text.count("{"), self.text.count("}"))


if __name__ == "__main__":
    unittest.main()
