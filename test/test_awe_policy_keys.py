"""Guard: the AWE policy keys join across the registry database and the AWE database.

An approval is routed by policy_key across two databases seeded by different files:
  * registry: g2p_registry_awe_policy_configurations binds the DA register (change requests) and its intake form
    (registrations) to a policy_key (meta_data/awe-integration/g2p_registry_awe_policy_configurations.sql)
  * AWE: approval_policy, approval_stage and approver_rule (awe_meta_data/)
Nothing checks the join at runtime: a binding to a key the AWE does not have leaves the change request or intake
without an approval, and the stage and rule seeds insert only WHERE EXISTS their policy or stage, so a mistyped id
inserts nothing.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "da-extension/src/openg2p_registry_da_extension"
META = EXT / "meta_data"
AWE = EXT / "awe_meta_data"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def text(path):
    return re.sub(r"--[^\n]*", "", path.read_text(encoding="utf-8"))


def rows(table):
    """The text of every INSERT INTO table in meta_data, up to its ON CONFLICT."""
    for path in sorted(META.rglob("*.sql")):
        yield from re.findall(rf'INSERT\s+INTO\s+"public"\."{table}"(.*?)ON\s+CONFLICT', text(path), re.S)


def test_registry_bindings_join_the_awe_policies():
    registers = {i for r in rows("g2p_register_definitions") for i in re.findall(rf"\('({UUID})','[A-Za-z]+','", r)}
    forms = {f: reg for r in rows("g2p_intake_form_definitions")
             for f, reg in re.findall(rf"\('({UUID})','({UUID})'", r)}
    bindings = re.findall(
        rf"\('({UUID})',\s*'(REGISTER|INTAKE_FORM|SECTION)',\s*'({UUID})',\s*'([^']*)',\s*'([^']*)',\s*'([^']+)',"
        r"\s*'([^']+)'", text(META / "awe-integration/g2p_registry_awe_policy_configurations.sql"))
    policies = {pid: (key, status, artifact) for pid, key, status, artifact in re.findall(
        rf"\('({UUID})', '([^']+)', \d+, '[^']*', NULL::text, '([a-z]+)', '([^']+)'",
        text(AWE / "10_approval_policy.sql"))}
    stages = {sid: (pid, int(order)) for sid, pid, order in re.findall(
        rf"\('({UUID})', '({UUID})', (\d+), '", text(AWE / "20_approval_stage.sql"))}
    rules = re.findall(rf"\('({UUID})', '({UUID})', 'user', '", text(AWE / "30_approver_rule.sql"))
    assert len(registers) == 3 and len(forms) == 1 and len(bindings) == 2
    assert len(policies) == 2 and len(stages) == 4 and len(rules) == 8

    by_key = {key: (status, artifact) for key, status, artifact in policies.values()}
    problems = []
    for config_id, scope, register, form, section, policy_type, key in bindings:
        if register not in registers:
            problems.append((config_id, "unknown register", register))
        if scope == "INTAKE_FORM" and forms.get(form) != register:
            problems.append((config_id, "intake form not of this register", form))
        if key not in by_key:
            problems.append((config_id, "no AWE policy", key))
        elif by_key[key] != ("active", policy_type):
            problems.append((config_id, "policy not active or of another artifact type", key, by_key[key]))
    for pid, (key, _, _) in policies.items():
        orders = sorted(order for p, order in stages.values() if p == pid)
        if orders != list(range(1, len(orders) + 1)) or not orders:
            problems.append(("policy", "stages not 1..n", key, orders))
    problems += [("stage", "no AWE policy", sid) for sid, (pid, _) in stages.items() if pid not in policies]
    problems += [("rule", "no such stage", rid, sid) for rid, sid in rules if sid not in stages]
    problems += [("stage", "no approver rule", sid) for sid in stages if sid not in {s for _, s in rules}]
    assert {key for *_, key in bindings} == {key for key, _, _ in policies.values()}
    assert not problems, problems
