import functools
import logging

from openg2p_fastapi_common.context import dbengine
from openg2p_registry_core.services import G2PDocumentService, G2PIntakeFormDataService
from sqlalchemy.ext.asyncio import async_sessionmaker

_logger = logging.getLogger("g2p-intake-form-data-service")

# The platform readers that return intake section payloads. Every screen that
# renders a submission goes through one of them, so one left out is a screen
# that silently loses the photo.
SECTION_PAYLOAD_READERS = (
    "get_intake_form_submission",
    "get_submission_payload",
    "get_tab_records",
)

_INSTALLED_MARKER = "_da_resolves_record_image_urls"


async def attach_record_image_urls(section_payloads) -> None:
    """Add record_image_url to every intake record carrying a document id.

    Best-effort: a submission that cannot be shown with its photo is still
    worth showing, so a failure here is logged rather than turned into a failed
    read of the whole submission.
    """
    records = [
        record
        for item in (section_payloads or [])
        for record in (getattr(item, "records", None) or [])
        if record.get("record_image_document_id")
    ]
    if not records:
        return

    try:
        # A second short-lived session: the platform's readers close theirs
        # before returning, and one batched lookup for the whole submission is
        # cheaper than threading a session through every wrapped reader.
        session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
        async with session_maker() as session:
            urls = await G2PDocumentService.get_component().get_document_urls(
                session,
                [record["record_image_document_id"] for record in records],
            )
    except Exception as error:
        _logger.warning(f"Could not resolve intake record image URLs: {error}")
        return

    for record in records:
        # get_document_urls skips ids it cannot find; leave those without a URL
        # rather than writing None over a key the UI treats as present.
        url = urls.get(record["record_image_document_id"])
        if url:
            record["record_image_url"] = url


def _with_record_image_urls(reader):
    @functools.wraps(reader)
    async def wrapper(*args, **kwargs):
        result = await reader(*args, **kwargs)
        # get_tab_records returns the list of section payloads directly; the
        # other two wrap it in a SubmissionResponsePayload.
        await attach_record_image_urls(getattr(result, "section_payloads", result))
        return result

    setattr(wrapper, _INSTALLED_MARKER, True)
    return wrapper


def install_record_image_url_resolution() -> None:
    """Make intake submission reads resolve the record photo into a URL.

    The platform builds intake section payloads with _serialize_model, which
    emits mapped columns only. record_image_url is not a column -- it exists
    solely as a presigned URL added at read time -- so a photo captured during
    intake comes back as a bare document_id and every consumer that renders a
    picture gets nothing to render.

    That is what makes the record photo invisible on the approval screen
    (/tasks/intake-form/<register>/<submission_id>): it renders the same intake
    sections, and the photo section's header-section widget draws ``imageUrl``
    only. The same blank shows when a saved photo
    section is reopened on a draft, for the same reason.

    Every register-side read path resolves these keys already --
    G2PRegisterService, G2PRegisterHierarchicalService, and for the detail
    view's edit flow G2PRegisterChangeRequestService, which does exactly this
    over its change payloads. The intake read path is the one that was missed,
    so this restores parity rather than inventing a convention.

    WHY WRAP THE CLASS AND NOT SUBCLASS IT
    --------------------------------------
    Registering a G2PIntakeFormDataService subclass does not work.
    BaseComponent.get_component returns the FIRST registered instance that
    isinstance-matches, and openg2p_registry_staff_api.main constructs
    CoreInitializer() -- which builds the platform's own instance -- before
    ExtensionsInitializer(). A subclass registered from this extension always
    lands second and nothing ever resolves to it. Wrapping the methods on the
    class instead applies to whichever instance wins that race.

    Idempotent: the extension Initializer can run more than once per process.
    Raises rather than silently doing nothing if a reader is gone, so an
    RP_VERSION bump that renames one surfaces at startup instead of as a
    photo that quietly stops appearing.
    """
    for name in SECTION_PAYLOAD_READERS:
        reader = getattr(G2PIntakeFormDataService, name, None)
        if reader is None:
            raise AttributeError(
                f"{G2PIntakeFormDataService.__name__}.{name} no longer exists; "
                "intake photo URL resolution needs re-anchoring to the pinned "
                "platform."
            )
        if getattr(reader, _INSTALLED_MARKER, False):
            continue
        setattr(G2PIntakeFormDataService, name, _with_record_image_urls(reader))
