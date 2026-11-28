"""Domain service of a DA's education records (child of DA).

A record is one row of the "Education" table: education level, passout year
and up to three certificates. Position, specialisation and joining date are
fields of the DA record ("Position and reporting"), not of a row.

What a certificate may be (file types, size, how many) is read from the file
column's options in the section metadata, the same options the form uses, so
the form and the API refuse the same files. That holds for a file sent inline
and for one uploaded first and sent by its document id.

Certificates: the platform's section file uploader covers a section's own file
widgets, not files inside a table row, so a new file arrives inline in the row
(base64, {"__type": "File", ...}) and is stored here the way core stores an
upload. The row keeps [{"document_id": ..., "name": ...}].
"""

import asyncio
import base64
import hashlib
import io
import json
import logging
import uuid
from collections import OrderedDict
from datetime import date

from openg2p_registry_core.services import G2PRegisterDomainService

from .domain_validation_utils import as_int, validation_error
from .ethiopian_calendar import gregorian_to_ethiopic

_logger = logging.getLogger("g2p-register-domain-service")

MAX_CERTIFICATES = 3
# Used when the section metadata names no limits for the file column.
DEFAULT_EXTENSIONS = ("pdf", "jpg", "jpeg", "png", "webp")
DEFAULT_MAX_BYTES = 2 * 1024 * 1024
# Passout year is an Ethiopian calendar year, like the year of birth.
MIN_PASSOUT_YEAR_EC = 1950
REQUIRED = (
    ("education_level", "Education level"),
    ("passout_year", "Passout year"),
)
_SKIP_ACTIONS = {"DELETE", "NO_CHANGE"}

# Stored files by content hash: a change request is validated when it is
# created and again before it is approved, and both must give one document.
_stored: "OrderedDict[str, dict]" = OrderedDict()
_STORED_MAX = 256
_pending_documents: list[dict] = []


def _json(value):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return None
    return value


def _is_blank(value) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _store_file(value: dict, created_by) -> dict:
    from openg2p_registry_core.config import Settings
    from openg2p_registry_core.helpers.document import get_document_handler
    from openg2p_registry_core.helpers.file_validation import validate_file_bytes
    from openg2p_registry_core.helpers.file_validation_profiles import get_upload_validation_profile
    from openg2p_registry_core.models.enum import DocumentBucket

    try:
        content = base64.b64decode(value.get("data") or "", validate=True)
    except ValueError:
        validation_error("Certificates & documents: a file could not be read. Attach it again, or choose another copy.")
    digest = hashlib.sha256(content).hexdigest()
    if digest in _stored:
        _stored.move_to_end(digest)
        return dict(_stored[digest])
    filename = value.get("name") or "certificate"
    content_type = value.get("type") or "application/octet-stream"
    profile = get_upload_validation_profile(DocumentBucket.DOCUMENTS, Settings.get_config(strict=False))
    if profile is not None:
        content_type = validate_file_bytes(content, profile, filename=filename).mime_type
    store_id = get_document_handler().upload(
        data=io.BytesIO(content), length=len(content), bucket=DocumentBucket.DOCUMENTS, content_type=content_type
    )
    document_id = str(uuid.uuid4())
    _pending_documents.append(
        {
            "document_id": document_id,
            "document_store_id": store_id,
            "source_filename": filename,
            "created_by": str(created_by or "system"),
        }
    )
    entry = {"document_id": document_id, "name": filename}
    _stored[digest] = entry
    while len(_stored) > _STORED_MAX:
        _stored.popitem(last=False)
    return dict(entry)


async def _save_pending_documents() -> None:
    """Record the stored files in the document table, in their own session."""
    if not _pending_documents:
        return
    from openg2p_fastapi_common.context import dbengine
    from openg2p_registry_core.models import G2PRegistryDocument
    from openg2p_registry_core.models.enum import DocumentBucket
    from sqlalchemy.ext.asyncio import async_sessionmaker

    rows, _pending_documents[:] = list(_pending_documents), []
    async with async_sessionmaker(dbengine.get(), expire_on_commit=False)() as session:
        for row in rows:
            session.add(G2PRegistryDocument(bucket=DocumentBucket.DOCUMENTS, **row))
        await session.commit()


def _find_file_column(node):
    """The "certificates" column of the table in a section's UI schema."""
    if isinstance(node, dict):
        if node.get("column-key") == "certificates":
            return node
        for value in node.values():
            found = _find_file_column(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_file_column(item)
            if found:
                return found
    return None


def file_limits(sections: list) -> dict:
    """What a certificate may be: the file column's "oan-file-rules" in the
    section metadata (accept, maxSize in bytes, maxFiles). The form reads the
    same options, so the form and the API refuse the same files."""
    limits = {"extensions": set(DEFAULT_EXTENSIONS), "max_bytes": DEFAULT_MAX_BYTES, "max_files": MAX_CERTIFICATES}
    for _name, schema, _is_list in sections or []:
        column = _find_file_column(_json(schema))
        if not column:
            continue
        # "oan-file-rules": the table's popup strips widget-data-options before the
        # widget sees the column, so the rules live under a key of their own.
        options = column.get("oan-file-rules") or column.get("widget-data-options") or {}
        accepted = {part.strip().lstrip(".").lower() for part in str(options.get("accept") or "").split(",")}
        accepted.discard("")
        if accepted:
            limits["extensions"] = accepted
        if as_int(options.get("maxSize")):
            limits["max_bytes"] = as_int(options.get("maxSize"))
        if as_int(options.get("maxFiles")):
            limits["max_files"] = as_int(options.get("maxFiles"))
        break
    return limits


def check_file(name: str, size: int | None, limits: dict) -> None:
    """Refuse a file of a type or size the certificates column does not take."""
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in limits["extensions"]:
        allowed = sorted(e.upper() for e in limits["extensions"])
        listed = (", ".join(allowed[:-1]) + " or " + allowed[-1]) if len(allowed) > 1 else "".join(allowed)
        validation_error(f"Certificates & documents: {name} cannot be attached here. Choose a {listed} file.")
    if size is not None and size > limits["max_bytes"]:
        megabytes = limits["max_bytes"] / 1048576
        validation_error(
            f"Certificates & documents: {name} is larger than {megabytes:g} MB. "
            "Choose a smaller file, or scan it again at a lower resolution."
        )


# Stored documents already checked, so a change request validated on creation
# and again before approval reads a referenced file once.
_checked_documents: "OrderedDict[str, bool]" = OrderedDict()


async def _attached_ids(record: dict) -> set[str]:
    """Document ids the stored row of this record already carries."""
    row_id = str(record.get("internal_record_id") or "").strip()
    if not row_id:
        return set()
    from openg2p_fastapi_common.context import dbengine
    from sqlalchemy import text

    found: set[str] = set()
    async with dbengine.get().connect() as conn:
        for table in ("g2p_register_qualifications", "g2p_intake_form_qualifications"):
            rows = await conn.execute(
                text(f'SELECT certificates FROM "public"."{table}" WHERE internal_record_id = :id'), {"id": row_id}
            )
            for (value,) in rows:
                stored = value if isinstance(value, list) else (_json(value) or [])
                for item in stored if isinstance(stored, list) else []:
                    if isinstance(item, dict) and item.get("document_id"):
                        found.add(str(item["document_id"]))
    return found


async def _check_reference(document_id: str, limits: dict) -> None:
    """A file uploaded first and sent by its id: it must exist and pass the
    same type and size rules as a file sent inline."""
    if document_id in _checked_documents:
        return
    from openg2p_fastapi_common.context import dbengine
    from openg2p_registry_core.helpers.document import get_document_handler
    from sqlalchemy import text

    async with dbengine.get().connect() as conn:
        row = (
            await conn.execute(
                text(
                    'SELECT document_store_id, bucket, source_filename FROM "public"."g2p_registry_documents" '
                    "WHERE document_id = :id"
                ),
                {"id": document_id},
            )
        ).first()
    if row is None:
        validation_error(
            "Certificates & documents: a file was not found in the registry. Upload it again, then attach it."
        )
    store_id, bucket, filename = row
    check_file(str(filename or "file"), None, limits)
    content = await asyncio.to_thread(get_document_handler().download, store_id, bucket)
    check_file(str(filename or "file"), len(content), limits)
    _checked_documents[document_id] = True
    while len(_checked_documents) > _STORED_MAX:
        _checked_documents.popitem(last=False)


async def _certificates(record: dict, limits: dict) -> None:
    if "certificates" not in record:
        return
    value = _json(record.get("certificates"))
    if value in (None, ""):
        record["certificates"] = None
        return
    items = [item for item in (_json(i) for i in (value if isinstance(value, list) else [value])) if isinstance(item, dict)]
    references = [str(item["document_id"]) for item in items if item.get("__type") != "File" and item.get("document_id")]
    # A file the row already carries was accepted under the rules of its day.
    attached = await _attached_ids(record) if references else set()
    kept = []
    for item in items:
        if item.get("__type") == "File":
            name = str(item.get("name") or "certificate")
            encoded = str(item.get("data") or "")
            check_file(name, (len(encoded) * 3) // 4 - encoded[-2:].count("="), limits)
            kept.append(_store_file(item, record.get("created_by")))
        elif item.get("document_id"):
            document_id = str(item["document_id"])
            if document_id not in attached:
                await _check_reference(document_id, limits)
            kept.append(
                {
                    "document_id": document_id,
                    "name": str(item.get("name") or item.get("source_filename") or "certificate"),
                }
            )
    if len(kept) > limits["max_files"]:
        validation_error(
            f"Certificates & documents: up to {limits['max_files']} files can be attached to one record. Remove one."
        )
    record["certificates"] = kept or None


def check_passout_year(record: dict) -> None:
    """A given passout year is a whole Ethiopian calendar year, not in the future."""
    if _is_blank(record.get("passout_year")):
        return
    this_year = gregorian_to_ethiopic(date.today())[0]
    year = as_int(record.get("passout_year"))
    if year is None or not MIN_PASSOUT_YEAR_EC <= year <= this_year:
        validation_error(
            f"Passout year: enter a year between {MIN_PASSOUT_YEAR_EC} and {this_year}, "
            "in the Ethiopian calendar."
        )
    record["passout_year"] = year


def _check(record: dict) -> None:
    missing = [label for field, label in REQUIRED if field in record and _is_blank(record.get(field))]
    if record.get("edit_action") == "ADD":
        missing = [label for field, label in REQUIRED if _is_blank(record.get(field))]
    if missing:
        validation_error("Required: Education: fill in " + ", ".join(missing) + ".")
    check_passout_year(record)


class G2PRegisterDomainServiceQualification(G2PRegisterDomainService):
    _KEYS = ("education_level", "passout_year")

    async def validate_domain_attributes(self, records: list[dict]):
        from .choice_check import validate_choices
        from .required_fields import DA_REGISTER_ID, load_sections

        # The dropdowns of the table are columns of a section of the DA register.
        sections = [s for s in await load_sections(DA_REGISTER_ID) if s[2]] if records else []
        limits = file_limits(sections)
        for record in records:
            if record.get("edit_action") in _SKIP_ACTIONS:
                continue
            _check(record)
            await validate_choices(record, sections)
            await _certificates(record, limits)
        await _save_pending_documents()

    async def pre_approve(self, change_request, session):
        # The stored change payload still holds a new file inline; replace it
        # with the document before the row is written to the register.
        from openg2p_registry_core.models import G2PRegisterChangeRequestPayload
        from sqlalchemy.orm.attributes import flag_modified

        payload = await session.get(G2PRegisterChangeRequestPayload, change_request.change_request_id)
        if payload and payload.change_payload:
            from .required_fields import DA_REGISTER_ID, load_sections

            limits = file_limits([s for s in await load_sections(DA_REGISTER_ID) if s[2]])
            for record in payload.change_payload:
                if record.get("edit_action") not in _SKIP_ACTIONS:
                    await _certificates(record, limits)
            await _save_pending_documents()
            flag_modified(payload, "change_payload")
        await super().pre_approve(change_request, session)

    def _joined(self, payload: dict, extra: list[str] | None) -> str:
        parts = [str(item).strip() for item in (extra or []) if str(item).strip()]
        parts.extend(str(payload.get(key) or "").strip() for key in self._KEYS if str(payload.get(key) or "").strip())
        return " ".join(parts).strip()

    def construct_search_text(self, payload: dict, extra: list[str] = None) -> str:
        return self._joined(payload, extra)

    def construct_record_name(self, payload: dict, extra: list[str] = None) -> str:
        return self._joined(payload, extra)
