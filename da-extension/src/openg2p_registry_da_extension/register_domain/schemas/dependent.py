from datetime import date
from typing import Optional

from openg2p_registry_core.schemas import (
    G2PIntakeFormSchemaBase,
    G2PRegisterBaseSchema,
    G2PRegisterHistorySchema,
)


class G2PSchemaDependent:
    member_name: Optional[str] = None
    relationship: Optional[str] = None
    date_of_birth: Optional[date] = None


class G2PRegisterSchemaDependent(G2PRegisterBaseSchema, G2PSchemaDependent):
    """Family member / dependent of a DA."""


class G2PRegisterHistorySchemaDependent(G2PRegisterHistorySchema, G2PSchemaDependent):
    """History of a family member / dependent."""


class G2PIntakeFormSchemaDependent(G2PIntakeFormSchemaBase, G2PRegisterBaseSchema, G2PSchemaDependent):
    """Family member / dependent on an intake submission."""
