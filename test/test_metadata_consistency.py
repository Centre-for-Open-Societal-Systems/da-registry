"""Guard: every field name the metadata, templates and reporting views use is a column of the model.

A field name that does not match a column fails silently: the platform saves nothing for a widget bound to a
missing column, a search or filter on it finds nothing, a DCI field is always empty, and a reporting view breaks
only when it is refreshed in a cluster. This test reads the files statically, so it needs no database or platform
image and runs on every push in under a second. It is the base the other guard tests (test_search_text.py) read
the model from.

The model's columns are read from source with ast, without importing it:
  * the DA extension's mixins (register_domain/models/*.py)
  * the platform base classes the registers inherit from (CORE_COLUMNS below)
"""

import ast
import re
from functools import cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "da-extension/src/openg2p_registry_da_extension"
MODELS = EXT / "register_domain/models"
META = EXT / "meta_data"
UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# The platform base classes' columns (openg2p_registry_core.models, g2p_register.py) at the pinned platform version.
# When the pin moves (ci/deploy/bump_pin.py), compare these with the new version's core models and update
# CORE_VERSION.
CORE_VERSION = "1.2.2-rc.614"
CORE_COLUMNS = {
    "G2PRegister": {
        "internal_record_id", "functional_record_id", "link_internal_record_id", "link_foundational_id",
        "record_name", "record_image_document_id", "created_by", "created_at", "last_approved_at",
        "last_approved_by", "search_text", "record_status", "record_status_reason"},
    "G2PPerson": {
        "foundational_id", "first_name", "middle_name", "last_name", "given_name", "prefix", "suffix", "gender",
        "birth_date", "phone_numbers", "emails", "marital_status", "occupation", "income_level", "language_code",
        "education_level", "registration_date"},
    "G2PGeo": {
        "latitude", "longitude", "altitude", "plus_code", "address_line_1", "address_line_2", "postal_code",
        "country_code", "geo_lowest_level_value_id", "geo_code_hierarchy_json"},
}

# The Master Data lists the form's dropdowns read (widget-data-source params.attribute_id). They come from the
# openg2p-data pack, which db-seed bakes at OPENG2P_DATA_REF (docker/db-seed/Dockerfile). These are the ids in
# packs/ETH-OAN at PACK_REF (codelists/ and domains/agriculture/), checked by hand; when the ref moves, check the
# new commit and update both.
PACK_REF = "34b239463cc38af8c028428df1eb52d786cc14c2"
PACK_LISTS = {"GENDER", "MARITAL_STATUS", "PREFIX", "DA_EDUCATION_LEVEL", "DA_SPECIALISATION", "DA_POSITION",
              "DA_SOURCE"}
# Lists the form uses that are not in the pack at PACK_REF. DA_RELATIONSHIP (the family members' Relationship,
# 90_dependents.sql) is on openg2p-data develop (PR #62) but after PACK_REF. Remove an entry once the pin has it:
# the test fails while a listed list is no longer missing.
KNOWN_NOT_IN_PACK = {"DA_RELATIONSHIP"}

# Fields the import template writes that are not columns of the section's register, so they are never stored.
# The Qualification register has no source column (the education row's source is the DA's). Either drop the field
# from the template or add the column (with a migration); then remove the entry: the test fails while a listed gap
# no longer exists.
KNOWN_UNSTORED = {("import_file_to_openg2p_da", "da_qualification", "source")}


@cache
def models():
    """{register mnemonic: columns} and {table name: register mnemonic}, read from the model source."""
    mixins, registers, tables = {}, {}, {}
    for path in sorted(MODELS.glob("*.py")):
        for node in ast.parse(path.read_text()).body:
            if not isinstance(node, ast.ClassDef):
                continue
            columns = {s.target.id for s in node.body if isinstance(s, ast.AnnAssign)
                       and isinstance(s.value, ast.Call) and getattr(s.value.func, "id", None) == "mapped_column"}
            bases = [ast.unparse(b) for b in node.bases]
            if not bases:
                mixins[node.name] = columns
            elif node.name.startswith("G2PRegister") and not node.name.startswith("G2PRegisterHistory"):
                mnemonic = node.name.removeprefix("G2PRegister")
                registers[mnemonic] = columns.union(*(CORE_COLUMNS.get(b, mixins.get(b, set())) for b in bases))
                for s in node.body:
                    if isinstance(s, ast.Assign) and getattr(s.targets[0], "id", None) == "__tablename__":
                        tables[s.value.value] = mnemonic
    return registers, tables


def columns(mnemonic):
    return models()[0][mnemonic]


def seed_sql():
    return {path.relative_to(META).as_posix(): path.read_text(encoding="utf-8") for path in sorted(META.rglob("*.sql"))}


@cache
def register_ids():
    """{register id: mnemonic} from the register definitions."""
    return {i: m for text in seed_sql().values() for i, m in re.findall(rf"\('({UUID})','([A-Za-z]+)'", text)
            if m in models()[0]}


@cache
def sections():
    """{section mnemonic: register mnemonic of the records the section holds (section_register_id)}."""
    ids = register_ids()
    return {mnemonic: ids[record_register] for text in seed_sql().values() for _, record_register, mnemonic in
            re.findall(rf"'({UUID})','\w+_section_\d+','({UUID})','(?:TRUE|FALSE)','(\w+)'", text)}


def test_core_columns_follow_the_platform_pin():
    pin = re.search(r"^ARG RP_VERSION=(\S+)$", (ROOT / "docker/staff-api/Dockerfile").read_text(), re.M)
    assert pin and pin.group(1) == CORE_VERSION, "Platform pin moved: re-check CORE_COLUMNS against its core models"


def test_model_source_yields_every_register():
    registers, tables = models()
    assert set(registers) == set(register_ids().values()) == {"DA", "Qualification", "Dependent"}
    assert set(tables) == {"g2p_register_das", "g2p_register_qualifications", "g2p_register_dependents"}
    assert {"internal_record_id", "foundational_id", "geo_lowest_level_value_id", "position", "kebele_code"} \
        <= columns("DA")
    assert {"da_identity", "da_service", "da_location", "da_qualification", "da_dependent"} <= set(sections())


def test_widgets_bind_to_columns():
    """A widget's data path is <register id>.<column>; a dialog table's is <register id>.records, and its columns'
    paths are bare column names of that register (one table per file)."""
    path = r"""widget-data-path['"]?\s*[,:]\s*['"]([^'"]+)['"]"""
    ids, bound, problems = register_ids(), set(), []
    for name, text in seed_sql().items():
        table = None
        for value in re.findall(path, text):
            register, _, field = value.rpartition(".")
            if register:
                assert register in ids, (name, value)
                if field == "records":
                    assert table in (None, ids[register]), (name, "more than one table in the file")
                    table = ids[register]
                    continue
                mnemonic = ids[register]
            else:
                assert table, (name, "a bare data path outside a table", value)
                mnemonic = table
            bound.add((mnemonic, field))
            if field not in columns(mnemonic):
                problems.append((name, mnemonic, field))
    assert {("DA", "position"), ("Qualification", "passout_year"), ("Dependent", "relationship")} <= bound
    assert not problems, problems


def test_register_schemas_name_columns():
    """deduplicate_schema, search_result_schema and filter_schema of g2p_register_schemas: a name that is not a
    column dedups, lists or filters on nothing."""
    ids, found, problems = register_ids(), set(), []
    for name, text in seed_sql().items():
        for statement in text.split(";\n"):
            if "g2p_register_schemas" not in statement:
                continue
            mnemonics = re.findall(r"""register_mnemonic"\s*=\s*'(\w+)'""", statement)
            for match in re.finditer(r"""field_name['"]\s*[,:]\s*['"](\w+)['"]""", statement):
                before = [ids[i] for i in re.findall(UUID, statement[:match.start()]) if i in ids]
                mnemonic = before[-1] if before else mnemonics[0]
                found.add((mnemonic, match.group(1)))
                if match.group(1) not in columns(mnemonic):
                    problems.append((name, mnemonic, match.group(1)))
    assert {("DA", "foundational_id"), ("DA", "kebele_code"), ("Qualification", "passout_year"),
            ("Dependent", "member_name")} <= found
    assert not problems, problems


def test_templates_read_columns():
    """The DCI response (openg2p_da_to_dci) reads the DA record; the import template writes each intake section's
    fields, which must be columns of the register the section holds."""
    templates = EXT / "templates"
    dci = set(re.findall(r"\bda\.get\('(\w+)'\)", (templates / "openg2p_da_to_dci.json.j2").read_text()))
    assert {"functional_record_id", "foundational_id", "kebele_code"} <= dci
    problems = [("openg2p_da_to_dci", "DA", f) for f in sorted(dci - columns("DA"))]
    text = (templates / "import_file_to_openg2p_da.json.j2").read_text()
    by_section = {section: set(re.findall(r'^\s+"(\w+)":', body, re.M))
                  for section, body in re.findall(r'^  "(\w+)": \[\n(.*?)^  \]', text, re.S | re.M)}
    assert {"da_identity", "da_contact", "da_service", "da_qualification", "da_location"} == set(by_section)
    for section, fields in sorted(by_section.items()):
        assert section in sections(), section
        problems += [("import_file_to_openg2p_da", section, f) for f in sorted(fields - columns(sections()[section]))]
    new, fixed = set(problems) - KNOWN_UNSTORED, KNOWN_UNSTORED - set(problems)
    assert not new and not fixed, {"new": sorted(new), "fixed, remove from KNOWN_UNSTORED": sorted(fixed)}


def test_reporting_views_read_columns():
    sql = re.sub(r"--[^\n]*", "", (ROOT / "docker/db-seed/reporting_views.sql").read_text())
    aliases = {"da": "DA", "q": "Qualification"}
    assert re.search(r"FROM g2p_register_das da\b", sql) and re.search(r"FROM g2p_register_qualifications q\b", sql)
    read = {(aliases[a], f) for a, f in re.findall(r"\b(da|q)\.(\w+)", sql)}
    assert {("DA", "position"), ("DA", "geo_code_hierarchy_json"), ("Qualification", "passout_year")} <= read
    problems = sorted((m, f) for m, f in read if f not in columns(m))
    assert not problems, problems


def test_dropdowns_read_lists_of_the_pinned_pack():
    pin = re.search(r"^ARG OPENG2P_DATA_REF=(\S+)$", (ROOT / "docker/db-seed/Dockerfile").read_text(), re.M)
    assert pin and pin.group(1) == PACK_REF, "openg2p-data pin moved: re-check PACK_LISTS against the new commit"
    used = {a for text in seed_sql().values()
            for a in re.findall(r"""attribute_id['"]\s*[,:]\s*['"](\w+)['"]""", text)}
    assert {"DA_POSITION", "DA_SPECIALISATION", "DA_EDUCATION_LEVEL"} <= used
    missing = used - PACK_LISTS
    assert missing == KNOWN_NOT_IN_PACK, {"not in the pack": sorted(missing - KNOWN_NOT_IN_PACK),
                                          "now in the pack, remove": sorted(KNOWN_NOT_IN_PACK - missing)}
