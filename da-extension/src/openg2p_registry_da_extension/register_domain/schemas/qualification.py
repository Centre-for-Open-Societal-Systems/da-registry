from datetime import date
from typing import Optional

from openg2p_registry_core.schemas import (
    G2PIntakeFormSchemaBase,
    G2PRegisterBaseSchema,
    G2PRegisterHistorySchema,
)


class G2PSchemaQualification:
    education_level: Optional[str] = None
    specialisation: Optional[str] = None
    position: Optional[str] = None
    joined_date: Optional[date] = None
    passout_year: Optional[int] = None
    certificates: Optional[list] = None


class G2PRegisterSchemaQualification(G2PRegisterBaseSchema, G2PSchemaQualification):
    """Education & professional record of a DA."""


class G2PRegisterHistorySchemaQualification(G2PRegisterHistorySchema, G2PSchemaQualification):
    """History of an education & professional record."""


class G2PIntakeFormSchemaQualification(G2PIntakeFormSchemaBase, G2PRegisterBaseSchema, G2PSchemaQualification):
    """Education & professional record on an intake submission."""
