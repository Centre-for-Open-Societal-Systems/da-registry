"""The ECR names of the DA Registry images (oan-helm docs/release/naming-standard.md, section 6).

    eoan/da-registry/<image>[-<rpVersion>]:<version>-<branch>.<build>

    eoan/da-registry/staff-api-1.2.2-rc.614:1.0.0-develop.90     an OpenG2P platform role

<version> is in init.yaml at the root of this repository. <rpVersion>, the OpenG2P registry platform the images are
built on, is appVersion of helm/openg2p-da-registry/Chart.yaml, and every platform Dockerfile's ARG RP_VERSION
default equals it (test/test_image_names.py). Only the six images built on the platform carry -<rpVersion>, so a
platform bump starts new repositories for them. <build> is the Jenkins build number. The pipeline, the chart
packaging and the deploy all take the names from here.

Releases deployed before these names run openg2p/da-registry/<image>:<commit12> or
eoan/da-registry/<image>-<rpVersion>:0.0.0-develop.<build>; legacy() names the first, the settings template
of a new repository.

    image_names.py tag <branch> <build>     the image tag of a build
    image_names.py repository <image>       the ECR repository of an image, without the registry host
    image_names.py legacy <image>           its repository before eoan
    image_names.py platform                 rpVersion

Standard library only: it runs on the Jenkins agent's stock Python.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "helm/openg2p-da-registry/Chart.yaml"
INIT = ROOT / "init.yaml"
PATH = "eoan/da-registry"
LEGACY_PATH = "openg2p/da-registry"
# The OpenG2P registry platform roles: their images are built FROM openg2p/openg2p-registry-<role>:<rpVersion>.
PLATFORM_IMAGES = ("staff-api", "partner-api", "celery", "db-seed", "sanity-tests", "staff-ui")
# DA builds no connector and no dashboard (DA records agents, not farmers), so every image is a platform role.
OTHER_IMAGES = ()
RENAMED = {}
VERSION = re.compile(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")
LINE = re.compile(r"""^(?P<key>[A-Za-z][A-Za-z0-9_]*)\s*:\s*(?P<value>"[^"]*"|'[^']*'|[^#\s]+)\s*(?:#.*)?$""")


def read_init(path=None):
    """init.yaml as {field: value}: flat `key: value` lines and comments, a version and nothing else."""
    path = Path(path or INIT)
    fields = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        found = LINE.match(line)
        if not found or found.group("key") != "version" or "version" in fields:
            raise ValueError("%s line %d: only one `version: N.N.N` line is allowed" % (path.name, number))
        fields["version"] = found.group("value").strip("\"'")
    if not VERSION.fullmatch(fields.get("version", "")):
        raise ValueError("%s needs `version: N.N.N` (a release, no pre-release words)" % path.name)
    return fields


def platform():
    match = re.search(r"""(?m)^appVersion:\s*["']?([^"'\s]+)""", CHART.read_text(encoding="utf-8"))
    if not match:
        raise ValueError("%s has no appVersion" % CHART.name)
    return match.group(1)


def repository(image):
    image = RENAMED.get(image, image)
    if image in PLATFORM_IMAGES:
        return "%s/%s-%s" % (PATH, image, platform())
    if image in OTHER_IMAGES:
        return "%s/%s" % (PATH, image)
    raise ValueError("unknown image %s" % image)


def legacy(image):
    """The image's repository before eoan: the template of a new repository's lifecycle policy."""
    image = RENAMED.get(image, image)
    if image not in PLATFORM_IMAGES + OTHER_IMAGES:
        raise ValueError("unknown image %s" % image)
    return "%s/%s" % (LEGACY_PATH, image)


def tag(branch, build):
    slug = re.sub(r"[^a-z0-9]+", "-", str(branch).lower()).strip("-")
    if not slug or not re.fullmatch(r"[1-9]\d*", str(build)):
        raise ValueError("an image tag needs a branch and a build number")
    return "%s-%s.%s" % (read_init()["version"], slug, build)


if __name__ == "__main__":
    try:
        if len(sys.argv) == 4 and sys.argv[1] == "tag":
            print(tag(sys.argv[2], sys.argv[3]))
        elif len(sys.argv) == 3 and sys.argv[1] in ("repository", "legacy"):
            print((repository if sys.argv[1] == "repository" else legacy)(sys.argv[2]))
        elif len(sys.argv) == 2 and sys.argv[1] == "platform":
            print(platform())
        else:
            sys.exit("usage: image_names.py tag <branch> <build> | repository <image> | legacy <image> | platform")
    except (ValueError, OSError) as error:
        sys.exit("FAIL: %s" % error)
