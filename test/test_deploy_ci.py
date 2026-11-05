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
        (self.root / "test").mkdir()
        (self.root / "docker/staff-api").mkdir(parents=True)
        (self.root / "docker/local-dev/data-loaders").mkdir(parents=True)
        shutil.copy(ROOT / "ci/deploy/oan-chart.json", self.root / "ci/deploy/oan-chart.json")
        shutil.copy(ROOT / "test/test_oan_chart.py", self.root / "test/test_oan_chart.py")
        shutil.copy(ROOT / "Jenkinsfile", self.root / "Jenkinsfile")
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
        self.assertIn('RP_VERSION     = "1.2.2-rc.700"', text("Jenkinsfile"))
        self.assertIn('self.assertEqual(pin["version"], "1.0.0-dev.21")', text("test/test_oan_chart.py"))
        self.assertIn("ARG RP_VERSION=1.2.2-rc.700", text("docker/staff-api/Dockerfile"))
        self.assertIn("ARG RP_VERSION=1.2.2-rc.700", text("docker/local-dev/data-loaders/Dockerfile"))
        self.assertEqual(sorted(changed), sorted(["Jenkinsfile", "test/test_oan_chart.py", "docker/staff-api/Dockerfile",
                                                  "docker/local-dev/data-loaders/Dockerfile"]))

    def test_values_only_change_leaves_platform_files_alone(self):
        digest = self.publish(self.pinned["version"], self.pinned["platformVersion"], values=b"registry: {x: 1}\n")
        self.pinned["sha256"] = digest
        new, _ = self.propose()
        self.assertEqual(self.bump.update_companions(self.pinned, new["registry"], root=self.root), [])


def load_propose():
    spec = importlib.util.spec_from_file_location("propose_under_test", ROOT / "ci/deploy/propose_pin_pr.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProposePullRequestTests(unittest.TestCase):
    """The last Jenkins stage: opens the pin pull request, with a stand-in git and GitHub."""
    TOKEN = "tok-SECRET-123"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for rel in ("ci/deploy", "test", "docker/staff-api"):
            (self.root / rel).mkdir(parents=True)
        shutil.copy(ROOT / "ci/deploy/oan-chart.json", self.root / "ci/deploy/oan-chart.json")
        shutil.copy(ROOT / "test/test_oan_chart.py", self.root / "test/test_oan_chart.py")
        shutil.copy(ROOT / "Jenkinsfile", self.root / "Jenkinsfile")
        shutil.copy(ROOT / "docker/staff-api/Dockerfile", self.root / "docker/staff-api/Dockerfile")
        self.mod = load_propose()
        self.bump = load_bump()
        self.bump.PROFILE = self.root / "ci/deploy/oan-chart.json"
        self.bump.ROOT = self.root
        old = json.loads(self.bump.PROFILE.read_text(encoding="utf-8"))
        new = json.loads(json.dumps(old))
        pin = new["registry"]
        pin["version"] = "1.0.0-dev.21"
        pin["platformVersion"] = "1.2.2-rc.700"
        pin["sha256"] = "a" * 64
        pin["values"]["sha256"] = "b" * 64
        pin["repository"] = "https://raw.githubusercontent.com/Centre-for-Open-Societal-Systems/oan-helm/" + "e" * 40 + "/repository/"
        pin["values"]["url"] = pin["repository"][:-len("repository/")] + pin["values"]["path"]
        self.new = new
        self.proposal_result = (new, "newer chart 1.0.0-dev.21 released (pinned 1.0.0-dev.20)")
        self.bump.proposal = lambda old_profile: self.proposal_result
        self.cmds = []
        self.calls = []
        self.exists = ""          # what `git ls-remote` prints
        self.pulls = (200, [])    # answer to the pull request list
        self.create = (201, {"html_url": "https://github.com/o/r/pull/7"})
        self.fail_on = None       # a label whose command should fail

    def runner(self, cmd, label=None, cwd=None, env=None, check=True):
        self.cmds.append((label or cmd[0], cmd))
        if label == self.fail_on:
            raise RuntimeError("%s failed (exit 1):\nboom" % label)
        if label == "git remote get-url":
            return "https://github.com/o/r.git\n"
        if label == "git rev-parse":
            return "f" * 40 + "\n"
        if label == "git ls-remote":
            return self.exists
        return ""

    def call(self, method, path, token, payload=None):
        self.calls.append((method, path, payload))
        return self.pulls if method == "GET" else self.create

    def go(self, token=None):
        out = io.StringIO()
        import contextlib
        with contextlib.redirect_stdout(out):
            code = self.mod.propose(self.TOKEN if token is None else token, bump=self.bump, runner=self.runner,
                                    call=self.call, root=self.root)
        return code, out.getvalue()

    def labels(self):
        return [label for label, _ in self.cmds]

    def test_nothing_to_do_touches_neither_git_nor_github(self):
        self.proposal_result = (None, "up to date: chart 1.0.0-dev.20 and its values are unchanged on oan-helm main")
        code, out = self.go()
        self.assertEqual((code, self.cmds, self.calls), (0, [], []))
        self.assertIn("up to date", out)

    def test_a_needed_update_without_a_credential_proposes_nothing(self):
        code, out = self.go(token="")
        self.assertEqual(code, 3)
        self.assertEqual((self.cmds, self.calls), ([], []))
        self.assertIn("no GitHub credential", out)

    def test_full_proposal_flow(self):
        code, out = self.go()
        self.assertEqual(code, 0, out)
        labels = self.labels()
        order = ["git rev-parse", "the pin tests", "verified prefetch of the new pin", "git checkout -b", "git add",
                 "git commit", "git push", "git checkout", "git branch -D"]
        positions = [labels.index(name) for name in order]
        self.assertEqual(positions, sorted(positions))
        # the pin and the files that must agree with it were rewritten on disk
        self.assertIn("1.0.0-dev.21", (self.root / "ci/deploy/oan-chart.json").read_text())
        self.assertIn('RP_VERSION     = "1.2.2-rc.700"', (self.root / "Jenkinsfile").read_text())
        add = next(cmd for label, cmd in self.cmds if label == "git add")
        self.assertIn("ci/deploy/oan-chart.json", add)
        # the pull request goes to develop from a branch named for the version and values
        method, path, payload = self.calls[-1]
        self.assertEqual((method, path), ("POST", "/repos/o/r/pulls"))
        self.assertEqual(payload["base"], "develop")
        self.assertEqual(payload["head"], "bot/oan-chart-pin-1.0.0-dev.21-" + "b" * 8)
        self.assertIn("Merging this deploys to dev", payload["body"])
        self.assertIn("opened https://github.com/o/r/pull/7", out)
        # the workspace is restored to the commit the build checked out
        restore = next(cmd for label, cmd in self.cmds if label == "git checkout")
        self.assertEqual(restore[-1], "f" * 40)

    def test_the_token_is_never_printed_or_used_as_a_label(self):
        code, out = self.go()
        self.assertNotIn(self.TOKEN, out)
        self.assertNotIn(self.TOKEN, " ".join(self.labels()))
        push = next(cmd for label, cmd in self.cmds if label == "git push")
        self.assertNotIn(self.TOKEN, " ".join(push))                  # sent only as a base64 basic-auth header
        self.assertTrue(any(a.startswith("http.extraheader=AUTHORIZATION: basic ") for a in push))

    def test_an_existing_pull_request_is_not_proposed_again(self):
        self.pulls = (200, [{"html_url": "https://github.com/o/r/pull/3", "state": "closed"}])
        code, out = self.go()
        self.assertEqual(code, 0)
        self.assertIn("Already proposed", out)
        self.assertNotIn("git push", self.labels())
        self.assertEqual([c[0] for c in self.calls], ["GET"])

    def test_an_existing_branch_without_a_pull_request_only_opens_the_pull_request(self):
        self.exists = "abc\trefs/heads/bot/x\n"
        code, out = self.go()
        self.assertEqual(code, 0)
        self.assertNotIn("git push", self.labels())
        self.assertEqual(self.calls[-1][0], "POST")

    def test_failed_verification_pushes_nothing_and_restores_the_workspace(self):
        self.fail_on = "the pin tests"
        with self.assertRaisesRegex(RuntimeError, "the pin tests failed"):
            self.go()
        self.assertNotIn("git push", self.labels())
        self.assertIn("git checkout", self.labels())
        self.assertEqual([c[0] for c in self.calls], ["GET"])

    def test_github_refusing_to_list_pull_requests_is_reported(self):
        self.pulls = (403, {"message": "Resource not accessible by integration"})
        code, out = self.go()
        self.assertEqual(code, 4)
        self.assertIn("Pull requests write", out)
        self.assertNotIn("git push", self.labels())

    def test_github_refusing_to_create_the_pull_request_is_reported(self):
        self.create = (403, {"message": "Resource not accessible by integration"})
        code, out = self.go()
        self.assertEqual(code, 4)
        self.assertIn("is pushed; open the pull request", out)

    def test_repository_slug(self):
        slug = self.mod.slug_of
        self.assertEqual(slug("https://github.com/Centre-for-Open-Societal-Systems/da-registry.git\n"),
                         "Centre-for-Open-Societal-Systems/da-registry")
        self.assertEqual(slug("git@github.com:o/r.git"), "o/r")
        with self.assertRaises(ValueError):
            slug("https://gitlab.com/o/r.git")


# ---- the images go into the oan-helm chart ----------------------------------------------------------------------

def load_release():
    spec = importlib.util.spec_from_file_location("release_images_under_test", ROOT / "ci/deploy/release_images.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REG = "123456789012.dkr.ecr.ap-south-1.amazonaws.com"
REPO = "openg2p/da-registry"
REPOSITORY = "%s/%s" % (REG, REPO)
NEW_TAG = "0123456789ab"


def sample_values():
    """The shape of charts/openg2p-da-registry/values.yaml in oan-helm, reduced: every registry image is empty."""
    def img():
        return "    image:\n      repository: ''\n      tag: ''\n"
    return (
        "global:\n  baseDomain: development.oanstaging.com\n"
        "registry:\n"
        "  staffApi:\n    envVars:\n      A: 'b'\n" + img() + "    enabled: false\n"
        "# a comment at column 0 inside the registry block\n"
        "  partnerApi:\n" + img() + "    enabled: false\n"
        "  celeryWorker:\n" + img() + "    enabled: false\n"
        "  celeryBeat:\n" + img() + "    enabled: false\n"
        "  dbSeed:\n" + img() + "    loadSampleData: false\n    enabled: false\n"
        "  staffUi:\n" + img() + "    enabled: false\n"
        "  keycloak-init:\n    image:\n      repository: docker.io/x/y\n      tag: 1.0.0\n"
        "dashboardApi:\n  enabled: false\n  image:\n    repository: ''\n    tag: ''\n    digest: ''\n"
        "dashboardUi:\n  image:\n    repository: ''\n    tag: ''\n")


def release_digests():
    return dict((c, "sha256:" + ("%x" % (i + 1)) * 64) for i, c in enumerate(
        ["staff-api", "partner-api", "celery", "db-seed", "staff-ui"]))


class ImageValuesTests(unittest.TestCase):
    def setUp(self):
        self.r = load_release()
        self.tags = self.r.wanted(NEW_TAG, release_digests())

    def test_only_the_image_lines_of_the_six_components_change(self):
        old = sample_values()
        new = self.r.rewrite_values(old, self.tags, REPOSITORY)
        changed = [(a, b) for a, b in zip(old.split("\n"), new.split("\n")) if a != b]
        self.assertEqual(len(old.split("\n")), len(new.split("\n")))
        self.assertEqual(len(changed), 12)                         # repository + tag of six registry components
        self.assertTrue(all(b.lstrip().startswith(("repository:", "tag:")) for _, b in changed))
        self.assertIn("      repository: '%s/staff-api'" % REPOSITORY, new)
        self.assertIn("      tag: '%s@%s'" % (NEW_TAG, release_digests()["staff-api"]), new)
        self.assertIn("      tag: '%s@%s'" % (NEW_TAG, release_digests()["staff-ui"]), new)
        # untouched: the comment, the enabled flags, the init image, the dashboards (this repository does not build them)
        for kept in ("# a comment at column 0 inside the registry block", "tag: 1.0.0", "      A: 'b'", "repository: docker.io/x/y"):
            self.assertIn(kept, new)
        self.assertEqual(new.count("enabled: false"), old.count("enabled: false"))
        self.assertNotIn("enabled: true", new)
        self.assertEqual(new.split("dashboardApi:")[1], old.split("dashboardApi:")[1])

    def test_the_values_stay_valid_yaml_and_the_tags_are_strings(self):
        try:
            import yaml
        except ModuleNotFoundError:
            import sys
            sys.path.append(str(ROOT / "ci/deploy/vendor"))     # the deploy node's pure-Python PyYAML
            import yaml
        document = yaml.safe_load(self.r.rewrite_values(sample_values(), self.tags, REPOSITORY))
        for section, component in self.r.REGISTRY:
            image = document["registry"][section]["image"]
            self.assertEqual(image["repository"], REPOSITORY + "/" + component)
            self.assertEqual(image["tag"], "%s@%s" % (NEW_TAG, release_digests()[component]))
            self.assertIs(document["registry"][section]["enabled"], False)

    def test_both_celery_workloads_get_the_celery_digest(self):
        new = self.r.rewrite_values(sample_values(), self.tags, REPOSITORY)
        self.assertEqual(new.count("%s@%s" % (NEW_TAG, release_digests()["celery"])), 2)

    def test_rewriting_twice_changes_nothing(self):
        once = self.r.rewrite_values(sample_values(), self.tags, REPOSITORY)
        self.assertEqual(self.r.rewrite_values(once, self.tags, REPOSITORY), once)
        self.assertTrue(self.r.released_before(once, NEW_TAG))
        self.assertFalse(self.r.released_before(sample_values(), NEW_TAG))
        self.assertFalse(self.r.released_before(once, "ffffffffffff"))

    def test_a_missing_section_is_an_error_not_a_silent_skip(self):
        with self.assertRaises(ValueError):
            self.r.rewrite_values(sample_values().replace("  dbSeed:", "  dbSeedX:"), self.tags, REPOSITORY)

    def test_digests_are_read_and_validated(self):
        text = "".join("%s\t%s\n" % kv for kv in release_digests().items())
        self.assertEqual(self.r.read_digests(text), release_digests())
        for bad in ("staff-api\tlatest\n", "staff-api sha256:" + "a" * 64 + "\n"):
            with self.assertRaises(ValueError):
                self.r.read_digests(bad)

    def test_every_component_needs_a_digest_and_the_tag_a_commit(self):
        partial = dict(release_digests())
        del partial["db-seed"]
        with self.assertRaisesRegex(ValueError, "db-seed"):
            self.r.wanted(NEW_TAG, partial)
        with self.assertRaises(ValueError):
            self.r.wanted("latest", release_digests())


FORK = "fork-owner/oan-helm"


class FakeGitHub(object):
    """oan-helm as the stage sees it: the org repo (main, pull requests) and the fork (branch, commit)."""

    def __init__(self, release):
        self.r = release
        self.main_sha = "a" * 40
        self.text = sample_values()                 # values.yaml on the org repo's main
        self.branches = {}                          # fork branch -> text
        self.knows_commit = True                    # False: the fork cannot see main's head until it is synced
        self.pulls = []                             # open pull requests on the org repo
        self.calls = []
        self.refuse = {}                            # (method, path-prefix) -> status
        self.synced = False

    def __call__(self, method, path, token, payload=None):
        self.calls.append((method, path, payload))
        for (m, prefix), status in self.refuse.items():
            if method == m and prefix in path:
                return status, {"message": "refused"}
        org, fork = "/repos/%s" % self.r.SLUG, "/repos/%s" % FORK
        if path.startswith(org):
            rest = path[len(org):]
            if method == "GET" and rest == "/git/ref/heads/main":
                return 200, {"object": {"sha": self.main_sha}}
            if method == "GET" and rest.startswith("/contents/") and rest.endswith("?ref=main"):
                return 200, {"content": base64.b64encode(self.text.encode()).decode(), "sha": "blob1"}
            if method == "GET" and rest.startswith("/pulls?"):
                return 200, list(self.pulls)
            if method == "POST" and rest == "/pulls":
                pull = {"number": 11, "html_url": "https://github.com/%s/pull/11" % self.r.SLUG, "payload": payload}
                self.pulls.append(pull)
                return 201, pull
            if method == "PATCH" and rest.startswith("/pulls/"):
                self.pulls[0]["payload"] = payload
                return 200, {}
        elif path.startswith(fork):
            rest = path[len(fork):]
            if method == "POST" and rest == "/merge-upstream":
                self.synced = self.knows_commit = True
                return 200, {}
            if method == "POST" and rest == "/git/refs":
                name = payload["ref"][len("refs/heads/"):]
                if name in self.branches:
                    return 422, {"message": "Reference already exists"}
                if not self.knows_commit:
                    return 422, {"message": "Object does not exist"}
                self.branches[name] = self.text
                return 201, {}
            if method == "PATCH" and rest.startswith("/git/refs/heads/"):
                self.branches[rest[len("/git/refs/heads/"):]] = self.text
                return 200, {}
            if method == "GET" and rest.startswith("/contents/"):
                return 200, {"content": base64.b64encode(self.branches[rest.split("?ref=")[1]].encode()).decode(), "sha": "blob1"}
            if method == "PUT" and rest.startswith("/contents/"):
                self.branches[payload["branch"]] = base64.b64decode(payload["content"]).decode()
                return 200, {}
        raise AssertionError("unexpected call %s %s" % (method, path))


BRANCH = "bot/da-registry-images-" + NEW_TAG


class ImagePullRequestTests(unittest.TestCase):
    """ci/deploy/release_images.py opens the pull request and stops."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / ".build").mkdir()
        (self.root / ".build/image-digests.tsv").write_text("".join("%s\t%s\n" % kv for kv in release_digests().items()))
        self.r = load_release()
        self.gh = FakeGitHub(self.r)
        self.out = []
        self.env = {"IMAGE_TAG": NEW_TAG, "ECR_REGISTRY": REG, "ECR_BASE": REPO, "COMMIT_SUBJECT": "Add a field",
                    "SOURCE_COMMIT": NEW_TAG + "f" * 28, "BUILD_URL": "https://jenkins/job/7/"}
        self.tags = self.r.wanted(NEW_TAG, release_digests())

    def proposal(self):
        return self.r.Proposal("tok", "fork-owner", "oan-helm", call=self.gh, out=self.out.append)

    def run_stage(self, **overrides):
        env = dict(self.env, **overrides)
        return self.proposal().run(env, self.root, (self.root / ".build/image-digests.tsv").read_text())

    def methods(self):
        return [(m, p.split("?")[0].replace("/repos/%s" % self.r.SLUG, "ORG").replace("/repos/%s" % FORK, "FORK"))
                for m, p, _ in self.gh.calls]

    def test_the_branch_goes_to_the_fork_and_the_pull_request_to_the_org_main(self):
        url = self.run_stage()
        self.assertEqual(url, "https://github.com/%s/pull/11" % self.r.SLUG)
        calls = self.methods()
        order = [("POST", "FORK/git/refs"), ("PUT", "FORK/contents/charts/openg2p-da-registry/values.yaml"),
                 ("POST", "ORG/pulls")]
        positions = [calls.index(c) for c in order]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("%s@%s" % (NEW_TAG, release_digests()["staff-api"]), self.gh.branches[BRANCH])
        _, _, body = next(c for c in self.gh.calls if c[0] == "POST" and c[1].endswith("/pulls"))
        self.assertEqual((body["base"], body["head"]), ("main", "fork-owner:" + BRANCH))
        self.assertIn("DA registry images %s: Add a field" % NEW_TAG, body["title"])
        self.assertIn("https://jenkins/job/7/", body["body"])
        # nothing in the org repo is written, merged or waited for
        self.assertEqual([m for m, p in calls if p.startswith("ORG") and m not in ("GET", "POST")], [])
        self.assertFalse([c for c in calls if "merge" in c[1] and "merge-upstream" not in c[1] or "check-runs" in c[1]])

    def test_only_the_image_lines_of_the_chart_are_changed_on_the_branch(self):
        self.run_stage()
        old = sample_values().split("\n")
        new = self.gh.branches[BRANCH].split("\n")
        changed = [b for a, b in zip(old, new) if a != b]
        self.assertEqual(len(old), len(new))
        self.assertEqual(len(changed), 12)
        self.assertTrue(all(c.lstrip().startswith(("repository:", "tag:")) for c in changed))

    def test_a_commit_that_oan_helm_main_already_carries_opens_nothing(self):
        self.gh.text = self.r.rewrite_values(sample_values(), self.tags, REPOSITORY)
        proposal = self.proposal()
        self.assertIsNone(proposal.run(dict(self.env), self.root, (self.root / ".build/image-digests.tsv").read_text()))
        calls = self.methods()
        self.assertNotIn(("POST", "ORG/pulls"), calls)
        self.assertNotIn(("POST", "FORK/git/refs"), calls)
        self.assertIn("already in oan-helm main", proposal.note)

    def test_the_commit_that_merges_a_chart_pin_pull_request_opens_nothing(self):
        proposal = self.proposal()
        for files in ("ci/deploy/oan-chart.json\n", "ci/deploy/oan-chart.json"):
            self.assertIsNone(proposal.run(dict(self.env, CHANGED_FILES=files), self.root,
                                           (self.root / ".build/image-digests.tsv").read_text()))
            self.assertIn("only moves the chart pin", proposal.note)
        self.assertNotIn(("POST", "ORG/pulls"), self.methods())
        self.assertNotIn(("POST", "FORK/git/refs"), self.methods())

    def test_a_commit_with_code_or_a_pin_plus_anything_else_gets_its_pull_request(self):
        for files in ("ci/deploy/oan-chart.json\ndocker/staff-api/Dockerfile\n", "Jenkinsfile\n", ""):
            self.gh.branches.clear()
            self.gh.pulls.clear()
            self.assertTrue(self.run_stage(CHANGED_FILES=files), files)

    def test_the_changed_files_are_read_from_git_when_not_given(self):
        subprocess.run("git init -q . && git config user.email a@b && git config user.name n && mkdir -p ci/deploy"
                       " && echo 1 > ci/deploy/oan-chart.json && echo 1 > x && git add . && git commit -qm one"
                       " && echo 2 > ci/deploy/oan-chart.json && git commit -qam two", shell=True, cwd=str(self.root), check=True)
        self.assertEqual(self.r.changed_files(self.root, {}), ["ci/deploy/oan-chart.json"])
        self.assertIsNone(self.run_stage_in(self.root))

    def run_stage_in(self, root):
        return self.proposal().run(dict(self.env), root, (root / ".build/image-digests.tsv").read_text())

    def test_a_rebuild_with_new_digests_for_the_same_commit_is_still_skipped(self):
        other = dict(release_digests(), **{"staff-api": "sha256:" + "9" * 64})
        self.gh.text = self.r.rewrite_values(sample_values(), self.r.wanted(NEW_TAG, other), REPOSITORY)
        self.assertIsNone(self.run_stage())
        self.assertNotIn(("POST", "ORG/pulls"), self.methods())

    def test_the_next_commit_gets_its_own_pull_request(self):
        self.gh.text = self.r.rewrite_values(sample_values(), self.tags, REPOSITORY)    # the previous commit is merged
        url = self.run_stage(IMAGE_TAG="fedcba987654")
        self.assertTrue(url)
        self.assertIn("fedcba987654@", self.gh.branches["bot/da-registry-images-fedcba987654"])

    def test_a_left_over_branch_is_reset_and_the_open_pull_request_is_updated_not_duplicated(self):
        self.gh.branches[BRANCH] = "stale"
        self.gh.pulls.append({"number": 5, "html_url": "https://github.com/%s/pull/5" % self.r.SLUG, "payload": {}})
        url = self.run_stage()
        self.assertEqual(url, "https://github.com/%s/pull/5" % self.r.SLUG)
        calls = self.methods()
        self.assertIn(("PATCH", "FORK/git/refs/heads/" + BRANCH), calls)
        self.assertIn(("PATCH", "ORG/pulls/5"), calls)
        self.assertNotIn(("POST", "ORG/pulls"), calls)
        self.assertIn(NEW_TAG, self.gh.branches[BRANCH])

    def test_a_fork_that_has_not_seen_main_yet_is_synced_first(self):
        self.gh.knows_commit = False
        self.run_stage()
        self.assertTrue(self.gh.synced)
        self.assertIn(("POST", "ORG/pulls"), self.methods())
        self.assertIn("syncing", "\n".join(self.out))

    def test_a_fork_that_cannot_be_synced_is_reported(self):
        self.gh.knows_commit = False
        self.gh.refuse[("POST", "/merge-upstream")] = 409
        with self.assertRaises(self.r.Stop) as caught:
            self.run_stage()
        self.assertEqual(caught.exception.code, 4)
        self.assertIn("Sync fork", str(caught.exception))

    def test_a_token_without_access_is_reported_as_such(self):
        self.gh.refuse[("POST", "/git/refs")] = 403
        with self.assertRaises(self.r.Stop) as caught:
            self.run_stage()
        self.assertEqual(caught.exception.code, 4)
        self.assertIn("public_repo", str(caught.exception))
        self.assertNotIn("tok", str(caught.exception).replace("token", ""))

    def test_refused_pull_request_is_reported(self):
        self.gh.refuse[("POST", "/pulls")] = 403
        with self.assertRaises(self.r.Stop) as caught:
            self.run_stage()
        self.assertEqual(caught.exception.code, 4)

    def test_dry_run_changes_nothing(self):
        self.assertIsNone(self.run_stage(DRY_RUN="1"))
        self.assertEqual([m for m, _ in self.methods() if m != "GET"], [])

    def test_main_writes_the_pull_request_url_and_nothing_else(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.r.main(env=dict(self.env, GH_TOKEN="tok", GH_USER="fork-owner"), root=self.root, call=self.gh)
        self.assertEqual(code, 0, out.getvalue())
        self.assertEqual((self.root / ".build/oan-helm-pr.txt").read_text().strip(), "https://github.com/%s/pull/11" % self.r.SLUG)
        self.assertNotIn("tok", out.getvalue().replace("token", ""))

    def test_main_without_a_credential_is_exit_3_and_opens_nothing(self):
        for env in (dict(self.env), dict(self.env, GH_TOKEN="tok"), dict(self.env, GH_USER="fork-owner")):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = self.r.main(env=env, root=self.root, call=self.gh)
            self.assertEqual(code, 3)
        self.assertEqual(self.gh.calls, [])
        self.assertFalse((self.root / ".build/oan-helm-pr.txt").exists())

    def test_main_leaves_no_pull_request_file_when_the_commit_was_already_taken(self):
        self.gh.text = self.r.rewrite_values(sample_values(), self.tags, REPOSITORY)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = self.r.main(env=dict(self.env, GH_TOKEN="tok", GH_USER="fork-owner"), root=self.root, call=self.gh)
        self.assertEqual(code, 0)
        self.assertFalse((self.root / ".build/oan-helm-pr.txt").exists())


class PipelineWiringTests(unittest.TestCase):
    """Jenkinsfile: build (digests) -> deploy with rollback -> pin pull request -> oan-helm image pull request, last."""

    def setUp(self):
        self.text = (ROOT / "Jenkinsfile").read_text()

    def test_the_image_pull_request_is_the_last_stage_and_follows_the_deploy_and_the_pin(self):
        order = [self.text.index("stage('%s')" % n) for n in
                 ("Build & Push", "Deploy to Development", "Propose chart pin update", "Open oan-helm image PR")]
        self.assertEqual(order, sorted(order))
        self.assertEqual(self.text.count("stage('"), 8)
        self.assertLess(self.text.index("stage('Open oan-helm image PR')"), self.text.index("\n    post {"))

    def test_the_deploy_stage_still_fails_the_build(self):
        stage = self.text.split("stage('Deploy to Development')", 1)[1].split("stage('Propose chart pin update')", 1)[0]
        self.assertIn("bash ci/deploy-dev.sh", stage)
        self.assertNotIn("catchError(", stage)

    def test_digests_are_captured_from_the_push_output_for_every_component(self):
        build = self.text.split("stage('Build & Push')", 1)[1].split("stage('Deploy to Development')", 1)[0]
        self.assertIn(".build/image-digests.tsv", build)
        self.assertLess(build.index("docker push ${image}"), build.index("image-digests.tsv\n"))
        self.assertIn("grep -oE 'digest: sha256:[0-9a-f]{64}'", build)
        self.assertNotIn("aws ecr describe-images", self.text)          # no extra AWS permission is needed
        self.assertNotIn("\\{", build)                                    # an invalid Groovy escape

    def test_the_pull_request_stage_cannot_fail_the_build_and_needs_only_the_fork_credential(self):
        stage = self.text.split("stage('Open oan-helm image PR')", 1)[1].split("\n    post {", 1)[0]
        self.assertIn("catchError(buildResult: 'UNSTABLE', stageResult: 'UNSTABLE')", stage)
        self.assertIn("python3 ci/deploy/release_images.py", stage)
        self.assertIn("when { branch 'develop' }", stage)
        self.assertIn("OAN_HELM_FORK_CRED_ID", stage)
        for absent in ("KUBECONFIG", "helm upgrade", "kubectl", "docker "):
            self.assertNotIn(absent, stage)
        self.assertIn('OAN_HELM_FORK_CRED_ID = "oan-helm-fork-token"', self.text)
        self.assertIn('PIN_PR_CRED_ID = "oan-ci-app"', self.text)

    def test_the_stage_is_built_for_this_pipelines_names(self):
        self.assertIn('ECR_BASE       = "openg2p/da-registry"', self.text)
        release = (ROOT / "ci/deploy/release_images.py").read_text()
        self.assertIn('CHART = "openg2p-da-registry"', release)
        deploy = (ROOT / "ci/deploy-dev.sh").read_text()
        for section, component in load_release().REGISTRY:
            self.assertIn("{repository: '${IMAGE_REPOSITORY}/%s', tag: '${TAG}'}" % component, deploy)         # the tag the deploy sets is the tag the PR records

    def test_every_component_the_pipeline_builds_has_a_digest_line(self):
        for component in load_release().COMPONENTS:
            self.assertIn("name: '%s'," % component, self.text)

    def test_braces_balance(self):
        self.assertEqual(self.text.count("{"), self.text.count("}"))


if __name__ == "__main__":
    unittest.main()
