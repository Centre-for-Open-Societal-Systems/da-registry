"""A dropdown value must be one of its list.

The form offers each dropdown's choices from Master Data (the widget's
widget-data-source.params.attribute_id), but the server used to accept any
text a request carried, so a value such as gender "XYZ" reached the register
and later showed as a raw code. This check reads the same declaration the
form reads and refuses a value that is not in the list, naming the choices.

It runs for every channel from validate_domain_attributes (web save, change
request, file import, DA Services push). The file import and DA Services
enrichers have already turned labels into codes, so a correct row passes.
When Master Data cannot be read the check is skipped with a warning instead of
blocking every save; the list is cached for five minutes.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from openg2p_registry_core.services.g2p_attribute_value_validator import G2PAttributeValueValidator

from ...ingestion_pipeline.enricher_services import code_lists
from ...ingestion_pipeline.enricher_services.master_data_api import MasterDataUnavailable
from .domain_validation_utils import validation_error

_logger = logging.getLogger("da-choice-check")


def choice_fields(sections: list) -> dict[str, tuple[str, str]]:
    """{field: (attribute_id, label)} for every dropdown of the register's sections."""
    out: dict[str, tuple[str, str]] = {}
    for _name, schema, _is_list in sections:
        if isinstance(schema, str):
            try:
                schema = json.loads(schema)
            except ValueError:
                continue
        labels = code_lists._label_map(schema)
        for field, attribute_id in G2PAttributeValueValidator.field_map_from_ui_schema(schema).items():
            label = labels.get(field) or field.replace("_", " ").capitalize()
            out.setdefault(field, (attribute_id, label))
    return out


def _is_blank(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


async def validate_choices(record: dict, sections: list) -> None:
    """Refuse a dropdown value that is not in its Master Data list."""
    fields = choice_fields(sections)
    for field, (attribute_id, label) in fields.items():
        value = record.get(field)
        if _is_blank(value) or not isinstance(value, (str, int)):
            continue
        try:
            values = await asyncio.to_thread(code_lists.attribute_values, attribute_id)
        except MasterDataUnavailable as exc:
            _logger.warning("Choice check skipped for %s: %s", field, exc)
            continue
        ids = [k for k in values if not k.startswith("__")]
        if not ids:
            continue  # an empty or unknown list cannot say what is wrong
        text = str(value).strip()
        if text in ids or ("__code__" + text) in values:
            continue
        allowed = ", ".join(values[i] for i in ids)
        validation_error(f"{label}: '{text}' is not one of the choices. Choose one of: {allowed}.")
