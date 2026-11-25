"""Guard: every copy of the platform version equals the platform of the pinned central chart.

The images extend openg2p-registry-<role>:<RP_VERSION>, and the chart deploys them with its openg2p-registry
dependency, so the two must be the same platform. The copies: platformVersion in ci/deploy/oan-chart.json (read from
the chart archive), ARG RP_VERSION of every Dockerfile, RP_VERSION in ci/pipelines/dev.groovy, and appVersion and the
openg2p-registry dependency of helm/openg2p-da-registry/Chart.yaml. ci/deploy/bump_pin.py moves the first three
together; test_image_names.py checks the Dockerfiles against appVersion.
"""

import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_rp_pin_is_in_lockstep():
    pin = json.loads((ROOT / "ci/deploy/oan-chart.json").read_text())["registry"]["platformVersion"]
    copies = {}
    for path in sorted((ROOT / "docker").glob("**/Dockerfile")):
        for version in re.findall(r"^ARG RP_VERSION=(\S+)$", path.read_text(encoding="utf-8"), re.M):
            copies[path.relative_to(ROOT).as_posix()] = version
    assert len(copies) >= 5, copies
    jenkins = (ROOT / "Jenkinsfile").read_text(encoding="utf-8") + (ROOT / "ci/pipelines/dev.groovy").read_text()
    overrides = re.findall(r"""RP_VERSION\s*=\s*["']([^"']+)["']""", jenkins)
    assert overrides, "dev.groovy no longer sets RP_VERSION: update this test and the README"
    copies.update(("Jenkins RP_VERSION", version) for version in overrides)
    chart = yaml.safe_load((ROOT / "helm/openg2p-da-registry/Chart.yaml").read_text())
    copies["Chart.yaml appVersion"] = chart["appVersion"]
    copies.update(("Chart.yaml dependency", d["version"]) for d in chart["dependencies"]
                  if d["name"] == "openg2p-registry")
    assert "Chart.yaml dependency" in copies
    assert {path: version for path, version in copies.items() if version != pin} == {}, pin
