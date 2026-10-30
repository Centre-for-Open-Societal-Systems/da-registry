"""Move the pinned oan-helm chart (ci/deploy/oan-chart.json) to a new oan-helm release commit.

This automates the six manual steps in ci/deploy/README.md. It reads only from the immutable
oan-helm commit you name, computes the SHA-256 of the chart archive and of the public values,
cross-checks the archive against repository/SHA256SUMS at that commit, and rewrites the pin.
It never touches a cluster. A build does not run it: the pin changes in a reviewed pull request.

    python3 ci/deploy/bump_pin.py <40-hex oan-helm commit>             # show the new pin, change nothing
    python3 ci/deploy/bump_pin.py <commit> --write                     # update oan-chart.json
    python3 ci/deploy/bump_pin.py <commit> --version 1.0.0-dev.21      # default: releases/current.yaml

Standard library only; runs on the deploy node's stock Python.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import tarfile
import urllib.request

PROFILE = Path(__file__).with_name("oan-chart.json")
RAW = "https://raw.githubusercontent.com/Centre-for-Open-Societal-Systems/oan-helm/"
ROLE = "registry"
CHART = "openg2p-da-registry"
VALUES_PATH = "environments/dev/values/da.yaml"
LIMIT = 32 * 1024 * 1024


def get(uri):
    with urllib.request.urlopen(uri, timeout=30) as response:
        data = response.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("download exceeds the size limit: " + uri)
    return data


def chart_appversion(archive_bytes, name):
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as archive:
        member = archive.getmember(name + "/Chart.yaml")
        if not member.isfile() or member.size > 1024 * 1024:
            raise ValueError("unexpected Chart.yaml in the archive")
        text = archive.extractfile(member).read().decode("utf-8")
    found = re.search(r"(?m)^appVersion:\s*['\"]?([^'\"\s]+)", text)
    version = re.search(r"(?m)^version:\s*['\"]?([^'\"\s]+)", text)
    if not found or not version:
        raise ValueError("Chart.yaml has no appVersion/version")
    return version.group(1), found.group(1)


def new_pin(commit, version=None, fetch=get):
    """Return the updated profile (dict) for the oan-helm commit; `fetch` is injectable for tests."""
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("give the full 40-character oan-helm commit that contains the release")
    base = RAW + commit + "/"
    if version is None:
        current = fetch(base + "releases/current.yaml").decode("utf-8")
        found = re.search(r"(?m)^\s*" + re.escape(CHART) + r":\s*(\S+)\s*$", current)
        if not found:
            raise ValueError("releases/current.yaml at that commit has no " + CHART)
        version = found.group(1)
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:-[a-zA-Z0-9.-]+)?", version) or version.startswith("0.0.0"):
        raise ValueError("invalid chart version: " + version)

    archive_name = CHART + "-" + version + ".tgz"
    archive = fetch(base + "repository/" + archive_name)
    digest = hashlib.sha256(archive).hexdigest()
    sums = fetch(base + "repository/SHA256SUMS").decode("utf-8")
    listed = re.search(r"(?m)^([0-9a-f]{64})\s+\*?" + re.escape(archive_name) + r"\s*$", sums)
    if not listed:
        raise ValueError(archive_name + " is not listed in repository/SHA256SUMS at that commit")
    if listed.group(1) != digest:
        raise ValueError("archive digest does not match repository/SHA256SUMS at that commit")
    chart_version, platform = chart_appversion(archive, CHART)
    if chart_version != version:
        raise ValueError("archive contains chart " + chart_version + ", expected " + version)

    values = fetch(base + VALUES_PATH)
    profiles = json.loads(PROFILE.read_text(encoding="utf-8"))
    pin = profiles[ROLE]
    pin["repository"] = base + "repository/"
    pin["version"] = version
    pin["sha256"] = digest
    pin["platformVersion"] = platform
    pin["values"] = dict(pin.get("values") or {})
    pin["values"]["path"] = VALUES_PATH
    pin["values"]["sha256"] = hashlib.sha256(values).hexdigest()
    pin["values"]["url"] = base + VALUES_PATH
    return profiles


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("commit", help="40-character oan-helm commit that contains the chart release")
    parser.add_argument("--version", help="chart version (default: releases/current.yaml at that commit)")
    parser.add_argument("--write", action="store_true", help="update ci/deploy/oan-chart.json")
    args = parser.parse_args(argv)
    old = json.loads(PROFILE.read_text(encoding="utf-8"))
    new = new_pin(args.commit, args.version)
    text = json.dumps(new, indent=2) + "\n"
    for key in ("version", "sha256", "platformVersion"):
        print("%-16s %s -> %s" % (key, old[ROLE].get(key), new[ROLE][key]))
    print("%-16s %s -> %s" % ("values.sha256", old[ROLE]["values"].get("sha256"), new[ROLE]["values"]["sha256"]))
    print("%-16s %s -> %s" % ("commit", old[ROLE]["repository"].split("/oan-helm/")[1].split("/")[0], args.commit))
    if old[ROLE].get("platformVersion") != new[ROLE]["platformVersion"]:
        print("NOTE: platform version changed. Set RP_VERSION in the Jenkinsfile and the Dockerfile ARG to "
              + new[ROLE]["platformVersion"] + " in the same pull request.")
    if not args.write:
        print("\n(dry run: nothing written; add --write to update " + str(PROFILE.name) + ")")
        return 0
    PROFILE.write_text(text, encoding="utf-8")
    print("\nwrote " + str(PROFILE))
    print("next: python3 -m unittest discover -s test -p test_oan_chart.py && python3 ci/deploy/oan_chart.py prefetch registry")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (ValueError, OSError, KeyError, tarfile.TarError) as error:
        raise SystemExit("FAIL: " + str(error))
