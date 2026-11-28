"""Give a DA image's ECR repository the standard settings before the develop pipeline pushes to it.

    python3 ci/ecr_repository.py ensure <repository> <template repository>

Every eoan repository has immutable tags, scan on push, AES256 encryption and the tags owner=da-registry and
naming=eoan-standard (oan-helm docs/release/naming-standard.md).
- A missing repository (a new image, or every platform image after an rpVersion bump) is created with them, plus the
  lifecycle policy of the template (the image's repository before eoan) when that has one.
- An existing eoan repository that differs is corrected, and each change is printed: tag mutability and scanning are
  set, the two tags added. Encryption cannot change after creation, so a repository without AES256 fails the build.
- Nothing outside eoan/da-registry/ is ever changed. Nothing is created or changed by hand.

Needs the aws CLI with the pipeline's ECR credential. Standard library only. Exit codes: 0 ready, 1 failure.
"""
import json
import subprocess
import sys

REGION = "ap-south-1"
PREFIX = "eoan/da-registry/"
TAGS = [{"Key": "owner", "Value": "da-registry"}, {"Key": "naming", "Value": "eoan-standard"}]
SETTINGS = ["--image-tag-mutability", "IMMUTABLE", "--image-scanning-configuration", "scanOnPush=true",
            "--encryption-configuration", "encryptionType=AES256",
            "--tags"] + ["Key=%s,Value=%s" % (t["Key"], t["Value"]) for t in TAGS]


class Missing(Exception):
    pass


def aws(args):
    """stdout of `aws ecr <args>`; Missing for a repository or lifecycle policy that does not exist."""
    result = subprocess.run(["aws", "ecr", "--region", REGION] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            universal_newlines=True)
    if result.returncode:
        if "RepositoryNotFoundException" in result.stderr or "LifecyclePolicyNotFoundException" in result.stderr:
            raise Missing()
        raise RuntimeError("aws ecr %s failed: %s" % (args[0], result.stderr.strip().splitlines()[-1:] or ""))
    return result.stdout


def correct(found, call):
    """The changes made to an existing repository, so that it has the standard settings."""
    name, arn = found["repositoryName"], found["repositoryArn"]
    encryption = found.get("encryptionConfiguration", {}).get("encryptionType")
    if encryption != "AES256":
        raise RuntimeError("%s is encrypted with %s, not AES256: encryption cannot change after creation" %
                           (name, encryption))
    changes = []
    if found.get("imageTagMutability") != "IMMUTABLE":
        call(["put-image-tag-mutability", "--repository-name", name, "--image-tag-mutability", "IMMUTABLE"])
        changes.append("tag mutability %s -> IMMUTABLE" % found.get("imageTagMutability"))
    if not found.get("imageScanningConfiguration", {}).get("scanOnPush"):
        call(["put-image-scanning-configuration", "--repository-name", name,
              "--image-scanning-configuration", "scanOnPush=true"])
        changes.append("scan on push off -> on")
    have = {t["Key"]: t["Value"] for t in json.loads(call(["list-tags-for-resource", "--resource-arn", arn,
                                                            "--output", "json"])).get("tags", [])}
    wanted = [t for t in TAGS if have.get(t["Key"]) != t["Value"]]
    if wanted:
        call(["tag-resource", "--resource-arn", arn, "--tags", json.dumps(wanted)])
        changes.append("tags " + ", ".join("%s=%s" % (t["Key"], t["Value"]) for t in wanted))
    return changes


def ensure(name, template, call=aws):
    """'exists', 'corrected: <changes>' or 'created'."""
    if not name.startswith(PREFIX):
        raise ValueError("%s is not under %s: only eoan repositories are created or changed" % (name, PREFIX))
    try:
        found = json.loads(call(["describe-repositories", "--repository-names", name, "--output", "json"]))
        changes = correct(found["repositories"][0], call)
        return "corrected: " + "; ".join(changes) if changes else "exists"
    except Missing:
        pass
    call(["create-repository", "--repository-name", name] + SETTINGS)
    try:
        policy = json.loads(call(["get-lifecycle-policy", "--repository-name", template, "--output", "json"]))
    except Missing:
        policy = None
    if policy and policy.get("lifecyclePolicyText"):
        call(["put-lifecycle-policy", "--repository-name", name, "--lifecycle-policy-text", policy["lifecyclePolicyText"]])
    return "created"


def main(argv):
    if len(argv) != 4 or argv[1] != "ensure":
        print("usage: ecr_repository.py ensure <repository> <template repository>", file=sys.stderr)
        return 1
    try:
        print("%s: %s" % (argv[2], ensure(argv[2], argv[3])))
        return 0
    except (RuntimeError, OSError, ValueError, KeyError, IndexError) as error:
        print("FAIL: %s" % error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
