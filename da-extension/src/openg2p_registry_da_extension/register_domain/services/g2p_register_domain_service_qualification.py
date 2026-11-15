"""Domain service of a DA's education & professional records (child of DA).

A record is one row of the "Education & professional" table: education level,
specialisation, position, passout year, joining date and up to three
certificates.

Certificates: the platform's section file uploader covers a section's own file
widgets, not files inside a table row, so a new file arrives inline in the row
(base64, {"__type": "File", ...}) and is stored here the way core stores an
upload. The row keeps [{"document_id": ..., "name": ...}].
"""

import base64
import hashlib
import io
import json
import logging
import uuid
from collections import OrderedDict
from datetime import date

from openg2p_registry_core.services import G2PRegisterDomainService

from .domain_validation_utils import as_int, parse_date, validation_error
from .ethiopian_calendar import gregorian_to_ethiopic

_logger = logging.getLogger("g2p-register-domain-service")

MAX_CERTIFICATES = 3
# Passout year is an Ethiopian calendar year, like the year of birth.
MIN_PASSOUT_YEAR_EC = 1950
REQUIRED = (
    ("education_level", "Education level"),
    ("specialisation", "Specialisation"),
    ("position", "Position"),
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


def _certificates(record: dict) -> None:
    if "certificates" not in record:
        return
    value = _json(record.get("certificates"))
    if value in (None, ""):
        record["certificates"] = None
        return
    items = value if isinstance(value, list) else [value]
    kept = []
    for item in items:
        item = _json(item)
        if not isinstance(item, dict):
            continue
        if item.get("__type") == "File":
            kept.append(_store_file(item, record.get("created_by")))
        elif item.get("document_id"):
            kept.append(
                {
                    "document_id": str(item["document_id"]),
                    "name": str(item.get("name") or item.get("source_filename") or "certificate"),
                }
            )
    if len(kept) > MAX_CERTIFICATES:
        validation_error(
            f"Certificates & documents: up to {MAX_CERTIFICATES} files can be attached to one record. Remove one."
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
        validation_error("Required: Education & professional: fill in " + ", ".join(missing) + ".")
    check_passout_year(record)
    joined = parse_date(record.get("joined_date"))
    if joined is not None and joined > date.today():
        validation_error("Joining date: the date is in the future. Enter today or an earlier date.")


class G2PRegisterDomainServiceQualification(G2PRegisterDomainService):
    _KEYS = ("education_level", "specialisation", "position", "passout_year")

    async def validate_domain_attributes(self, records: list[dict]):
        from .choice_check import validate_choices
        from .required_fields import DA_REGISTER_ID, load_sections

        # The dropdowns of the table are columns of a section of the DA register.
        sections = [s for s in await load_sections(DA_REGISTER_ID) if s[2]] if records else []
        for record in records:
            if record.get("edit_action") in _SKIP_ACTIONS:
                continue
            _check(record)
            await validate_choices(record, sections)
            _certificates(record)
        await _save_pending_documents()

    async def pre_approve(self, change_request, session):
        # The stored change payload still holds a new file inline; replace it
        # with the document before the row is written to the register.
        from openg2p_registry_core.models import G2PRegisterChangeRequestPayload
        from sqlalchemy.orm.attributes import flag_modified

        payload = await session.get(G2PRegisterChangeRequestPayload, change_request.change_request_id)
        if payload and payload.change_payload:
            for record in payload.change_payload:
                if record.get("edit_action") not in _SKIP_ACTIONS:
                    _certificates(record)
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
