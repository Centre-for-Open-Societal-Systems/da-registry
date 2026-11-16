"""Image names: eoan/da-registry/<image>-<RP version>:<version>-<branch>.<build>, both versions from Chart.yaml.

Standard library only (runs on the Jenkins agent's stock Python).
    python3 -m unittest discover -s test -p test_image_names.py -v
"""
import importlib.util
from pathlib import Path
import re
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("image_names", ROOT / "ci/image_names.py")
image_names = importlib.util.module_from_spec(spec)
spec.loader.exec_module(image_names)
CHART = (ROOT / "helm/openg2p-da-registry/Chart.yaml").read_text(encoding="utf-8")
RP = re.search(r"(?m)^appVersion: (\S+)$", CHART).group(1)
VERSION = re.search(r"(?m)^version: (\S+)$", CHART).group(1)


class ImageNameTests(unittest.TestCase):
    def test_repository_carries_the_platform_version_of_the_chart(self):
        self.assertEqual(image_names.repository("staff-ui"), "eoan/da-registry/staff-ui-" + RP)

    def test_tag_is_the_chart_version_branch_and_build_number(self):
        self.assertEqual(image_names.tag("develop", 300), VERSION + "-develop.300")

    def test_tag_turns_any_branch_into_a_docker_tag(self):
        self.assertEqual(image_names.tag("feature/New_Field", "7"), VERSION + "-feature-new-field.7")

    def test_tag_refuses_a_missing_branch_or_build_number(self):
        for branch, build in (("develop", "0"), ("develop", ""), ("develop", "3a"), ("//", "5")):
            with self.assertRaises(ValueError):
                image_names.tag(branch, build)

    def test_command_line(self):
        for argv, expected in ((["tag", "develop", "12"], VERSION + "-develop.12"),
                               (["repository", "db-seed"], "eoan/da-registry/db-seed-" + RP)):
            done = subprocess.run([sys.executable, str(ROOT / "ci/image_names.py")] + argv, stdout=subprocess.PIPE,
                                  universal_newlines=True, check=True)
            self.assertEqual(done.stdout, expected + "\n")


if __name__ == "__main__":
    unittest.main()
