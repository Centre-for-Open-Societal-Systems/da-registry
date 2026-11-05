from datetime import date
from typing import Optional

from openg2p_registry_core.schemas import (
    G2PGeoHistorySchema,
    G2PGeoSchema,
    G2PIntakeFormSchemaBase,
    G2PPersonHistorySchema,
    G2PPersonSchema,
    G2PRegisterBaseSchema,
    G2PRegisterHistorySchema,
)



class G2PSchemaDA:
    birth_month_ec: Optional[int] = None
    birth_year_ec: Optional[int] = None

    mobile_number: Optional[str] = None
    telegram_number: Optional[str] = None
    alternate_number: Optional[str] = None
    email: Optional[str] = None

    specialisation: Optional[str] = None
    position: Optional[str] = None  # a DA_POSITION code from Master Data
    joined_date: Optional[date] = None
    source: Optional[str] = None  # a DA_SOURCE code from Master Data

    upstream_reference: Optional[str] = None
    upstream_approved_by: Optional[str] = None


    region_name: Optional[str] = None
    zone_name: Optional[str] = None
    woreda_name: Optional[str] = None
    kebele_name: Optional[str] = None
    region_code: Optional[str] = None
    zone_code: Optional[str] = None
    woreda_code: Optional[str] = None


class G2PRegisterSchemaDA(G2PRegisterBaseSchema, G2PPersonSchema, G2PGeoSchema, G2PSchemaDA):
    """Schema for the DA register."""


class G2PRegisterHistorySchemaDA(
    G2PRegisterHistorySchema,
    G2PPersonHistorySchema,
    G2PGeoHistorySchema,
    G2PSchemaDA,
):
    """Schema for DA history, including DA fields so approved changes stay visible."""


class G2PIntakeFormSchemaDA(
    G2PIntakeFormSchemaBase, G2PRegisterBaseSchema, G2PPersonSchema, G2PGeoSchema, G2PSchemaDA
):
    """Schema for the DA intake form."""
