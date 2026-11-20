"""ci/ecr_repository.py with a stand-in aws: new repositories get the standard settings, existing eoan ones are
corrected and say what changed, nothing outside eoan/da-registry/ is touched.

    python3 -m unittest discover -s test -p test_ecr_repository.py -v
"""
import importlib.util
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("ecr_repository", ROOT / "ci/ecr_repository.py")
ecr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ecr)
NEW = "eoan/da-registry/staff-api-1.2.2-rc.614"
OLD = "openg2p/da-registry/staff-api"
POLICY = '{"rules":[{"rulePriority":1}]}'
STANDARD = {"imageTagMutability": "IMMUTABLE", "imageScanningConfiguration": {"scanOnPush": True},
            "encryptionConfiguration": {"encryptionType": "AES256"}}
TAGS = [{"Key": "owner", "Value": "da-registry"}, {"Key": "naming", "Value": "eoan-standard"}]


class Aws:
    def __init__(self, existing, policies=None, tags=None):
        self.existing, self.policies, self.tags, self.calls = dict(existing), dict(policies or {}), tags or [], []

    def __call__(self, args):
        self.calls.append(args)
        if args[0] == "describe-repositories":
            if args[2] not in self.existing:
                raise ecr.Missing()
            repo = dict(self.existing[args[2]], repositoryName=args[2], repositoryArn="arn:" + args[2])
            return json.dumps({"repositories": [repo]})
        if args[0] == "get-lifecycle-policy":
            if args[2] not in self.policies:
                raise ecr.Missing()
            return json.dumps({"lifecyclePolicyText": self.policies[args[2]]})
        if args[0] == "list-tags-for-resource":
            return json.dumps({"tags": self.tags})
        return ""

    def names(self):
        return [c[0] for c in self.calls]


def option(call, name):
    return call[call.index(name) + 1]


class EnsureTests(unittest.TestCase):
    def test_a_standard_repository_is_left_alone(self):
        aws = Aws({NEW: STANDARD}, tags=TAGS)
        self.assertEqual(ecr.ensure(NEW, OLD, aws), "exists")
        self.assertEqual(aws.names(), ["describe-repositories", "list-tags-for-resource"])

    def test_a_missing_repository_gets_the_standard_settings_and_the_old_lifecycle_policy(self):
        aws = Aws({OLD: {}}, {OLD: POLICY})
        self.assertEqual(ecr.ensure(NEW, OLD, aws), "created")
        create = next(c for c in aws.calls if c[0] == "create-repository")
        self.assertEqual(option(create, "--repository-name"), NEW)
        self.assertEqual(option(create, "--image-tag-mutability"), "IMMUTABLE")
        self.assertEqual(option(create, "--image-scanning-configuration"), "scanOnPush=true")
        self.assertEqual(option(create, "--encryption-configuration"), "encryptionType=AES256")
        self.assertEqual(create[create.index("--tags") + 1:],
                         ["Key=owner,Value=da-registry", "Key=naming,Value=eoan-standard"])
        put = aws.calls[-1]
        self.assertEqual((put[0], option(put, "--repository-name"), option(put, "--lifecycle-policy-text")),
                         ("put-lifecycle-policy", NEW, POLICY))

    def test_without_a_template_policy_none_is_set(self):
        aws = Aws({})
        self.assertEqual(ecr.ensure(NEW, OLD, aws), "created")
        self.assertNotIn("put-lifecycle-policy", aws.names())

    def test_a_mutable_unscanned_untagged_repository_is_corrected_and_says_so(self):
        aws = Aws({NEW: {"imageTagMutability": "MUTABLE", "imageScanningConfiguration": {"scanOnPush": False},
                         "encryptionConfiguration": {"encryptionType": "AES256"}}})
        result = ecr.ensure(NEW, OLD, aws)
        self.assertEqual(result, "corrected: tag mutability MUTABLE -> IMMUTABLE; scan on push off -> on; "
                                 "tags owner=da-registry, naming=eoan-standard")
        mutability = next(c for c in aws.calls if c[0] == "put-image-tag-mutability")
        self.assertEqual(option(mutability, "--image-tag-mutability"), "IMMUTABLE")
        tagged = next(c for c in aws.calls if c[0] == "tag-resource")
        self.assertEqual(json.loads(option(tagged, "--tags")), TAGS)
        self.assertNotIn("create-repository", aws.names())

    def test_only_missing_tags_are_added(self):
        aws = Aws({NEW: STANDARD}, tags=[TAGS[0], {"Key": "team", "Value": "x"}])
        self.assertEqual(ecr.ensure(NEW, OLD, aws), "corrected: tags naming=eoan-standard")

    def test_encryption_that_is_not_aes256_fails(self):
        aws = Aws({NEW: dict(STANDARD, encryptionConfiguration={"encryptionType": "KMS"})})
        with self.assertRaises(RuntimeError):
            ecr.ensure(NEW, OLD, aws)
        self.assertEqual(aws.names(), ["describe-repositories"])

    def test_a_repository_outside_eoan_is_never_touched(self):
        aws = Aws({OLD: {"imageTagMutability": "MUTABLE"}})
        for name in (OLD, "eoan/farmer-registry/staff-api-1.2.2-rc.625"):
            with self.assertRaises(ValueError):
                ecr.ensure(name, OLD, aws)
        self.assertEqual(aws.calls, [])


if __name__ == "__main__":
    unittest.main()
