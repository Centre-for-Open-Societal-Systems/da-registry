"""Family members / dependents of a development agent: a child of DA.

One row per family member (name, relationship, date of birth); a DA can have
several, or none. Rows belong to the DA through the platform's
link_internal_record_id.
"""

from openg2p_registry_core.models import G2PRegister, G2PRegisterHistory
from openg2p_registry_core.models.g2p_intake_form import G2PIntakeForm
from sqlalchemy import Date, String
from sqlalchemy.orm import Mapped, mapped_column

from ..services import G2PRegisterDomainServiceDependent


class G2PDependent:
    member_name: Mapped[str] = mapped_column(String, nullable=True)
    relationship: Mapped[str] = mapped_column(String, nullable=True)  # DA_RELATIONSHIP
    date_of_birth: Mapped[str] = mapped_column(Date, nullable=True)


class G2PRegisterDependent(G2PRegister, G2PDependent):
    __tablename__ = "g2p_register_dependents"

    def get_search_text_fields(self) -> str:
        return G2PRegisterDomainServiceDependent().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        return G2PRegisterDomainServiceDependent().construct_record_name(self.to_dict())


class G2PRegisterHistoryDependent(G2PRegisterHistory, G2PDependent):
    __tablename__ = "g2p_register_history_dependents"


class G2PIntakeFormDependent(G2PIntakeForm, G2PRegister, G2PDependent):
    __tablename__ = "g2p_intake_form_dependents"

    def get_search_text_fields(self) -> str:
        return G2PRegisterDomainServiceDependent().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        return G2PRegisterDomainServiceDependent().construct_record_name(self.to_dict())
