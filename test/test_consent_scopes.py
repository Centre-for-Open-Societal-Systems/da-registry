"""Guard: every consent scope id the repository names is one the partner API can release.

At the pinned platform the partner API clamps a DCI search response to the consent's effective data scopes by
matching them against the TOP-LEVEL keys of the rendered search response (openg2p_registry_partner_api,
G2PDciService._clamp_record_fields): any other scope name matches nothing and releases nothing, without an error.
So a valid scope id is a top-level key of templates/openg2p_da_to_dci.json.j2, the DA register's outgoing DCI
template (meta_data/registry-outbound-messages-templates/outgoing_templates.sql, through its document in
register-metadata/g2p_registry_documents.sql). DA Services reads DAs through it.

The scope ids named here are the sanity DCI e2e's consented and denied scopes, helm values
registry.sanity.dataScopes / deniedScopes, which the platform chart passes to the sanity image as
SANITY_DATA_SCOPES / SANITY_DENIED_SCOPES. A consented scope must be releasable, or the e2e checks an empty
response. The denied scope (qualifications) is deliberately not a key: the whole record is under da_details, so a
partner that asks for anything else gets nothing.
"""

import json
import re
from pathlib import Path

import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "da-extension/src/openg2p_registry_da_extension"
VALUES = ROOT / "helm/openg2p-da-registry/values.yaml"
TEMPLATE = "openg2p_da_to_dci.json.j2"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"


def releasable_scopes():
    template = (EXT / "templates" / TEMPLATE).read_text(encoding="utf-8")
    return set(json.loads(Environment().from_string(template).render(expanded={})))


def named_scopes(key):
    sanity = yaml.safe_load(VALUES.read_text(encoding="utf-8"))["registry"]["sanity"]
    return {scope.strip() for scope in str(sanity.get(key) or "").split(",") if scope.strip()}


def test_consent_scope_ids_are_releasable():
    # outgoing_templates names the template by its g2p_registry_documents id.
    meta = EXT / "meta_data"
    outgoing = (meta / "registry-outbound-messages-templates/outgoing_templates.sql").read_text()
    document = re.search(rf"\('DA-OUT-TMPL-1','{UUID}','{UUID}','({UUID})'", outgoing).group(1)
    documents = (meta / "register-metadata/g2p_registry_documents.sql").read_text()
    assert re.search(rf"\('{document}','{re.escape(TEMPLATE)}','templates'", documents), document
    releasable = releasable_scopes()
    assert releasable == {"da_details"}, releasable
    consented, denied = named_scopes("dataScopes"), named_scopes("deniedScopes")
    assert consented == {"da_details"} and denied
    assert consented <= releasable, sorted(consented - releasable)
    assert not denied & releasable, sorted(denied & releasable)
