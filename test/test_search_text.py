"""Guard: search_text is built from real columns.

The register list and the DCI search match search_text (ILIKE), so a record is only findable by what its search_text
holds. Core fills it on save from each register's domain service (construct_search_text, reached through the
model's get_search_text_fields with the record's to_dict()). A field name that is not a column reads as None, and
the record silently stops being findable by it.
"""

import ast
import re
from pathlib import Path

from test_metadata_consistency import columns, models

ROOT = Path(__file__).resolve().parents[1]
EXT = ROOT / "da-extension/src/openg2p_registry_da_extension"
SERVICES = EXT / "register_domain/services"


def strings(node):
    return {e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}


def search_text_reads():
    """{register mnemonic: field names its construct_search_text reads}.

    The DA service lists its keys in construct_search_text; Qualification and Dependent read a class-level _KEYS
    through self._joined, so the methods and class attributes it reaches through self are followed."""
    reads = {}
    for path in sorted(SERVICES.glob("g2p_register_domain_service_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.ClassDef):
                continue
            methods = {f.name: f for f in node.body if isinstance(f, ast.FunctionDef)}
            attributes = {s.targets[0].id: strings(s.value) for s in node.body if isinstance(s, ast.Assign)
                          and isinstance(s.targets[0], ast.Name) and isinstance(s.value, (ast.List, ast.Tuple))}
            if "construct_search_text" not in methods:
                continue
            fields, queue, seen = set(), ["construct_search_text"], set()
            while queue:
                name = queue.pop()
                if name in seen:
                    continue
                seen.add(name)
                for n in ast.walk(methods[name]):
                    if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "get" and n.args \
                            and isinstance(n.args[0], ast.Constant):
                        fields.add(n.args[0].value)
                    elif isinstance(n, (ast.List, ast.Tuple)):
                        fields |= strings(n)
                    elif isinstance(n, ast.Attribute) and getattr(n.value, "id", None) == "self":
                        if n.attr in methods:
                            queue.append(n.attr)
                        fields |= attributes.get(n.attr, set())
            reads[node.name.removeprefix("G2PRegisterDomainService")] = fields
    return reads


def test_search_text_reads_model_columns():
    reads = search_text_reads()
    registers = set(models()[0])
    assert registers <= set(reads), registers - set(reads)
    assert {"functional_record_id", "foundational_id", "mobile_number", "kebele_name"} <= reads["DA"]
    assert reads["Qualification"] == {"education_level", "passout_year"}
    assert reads["Dependent"] == {"member_name", "relationship"}
    missing = {mnemonic: sorted(fields - columns(mnemonic)) for mnemonic, fields in reads.items()
               if mnemonic in registers and fields - columns(mnemonic)}
    assert not missing, missing


def test_raw_register_inserts_write_search_text():
    """Raw SQL does not fire the ORM listeners that fill search_text, so a row inserted that way must write it.

    test/sanity/sanity/data_seed.py does; any later loader must too. A Python file builds its column list apart from
    the INSERT, so the check is that the file names search_text. Unit-test fixtures (test/, da-extension/tests/)
    insert bare rows on purpose and are left out.
    """
    tables = "|".join(sorted(models()[1]))
    insert = re.compile(rf"INSERT\s+INTO\s+(?:\"?public\"?\.)?\"?(?:{tables})\b", re.I)
    writers = []
    skip = {".git", "node_modules", ".venv", "venv", "__pycache__"}
    fixtures = {ROOT / "test", ROOT / "da-extension/tests"}
    for path in sorted(p for p in ROOT.rglob("*") if p.suffix in (".py", ".sql", ".sh") and not skip & set(p.parts)
                       and p.parent not in fixtures):
        text = path.read_text(errors="ignore")
        if insert.search(text):
            writers.append((path.relative_to(ROOT).as_posix(), "search_text" in text))
    assert ("test/sanity/sanity/data_seed.py", True) in writers
    assert all(names for _, names in writers), [name for name, names in writers if not names]
