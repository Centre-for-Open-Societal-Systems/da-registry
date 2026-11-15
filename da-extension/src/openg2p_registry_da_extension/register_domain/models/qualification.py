"""Education & professional records of a development agent: a child of DA.

One row per record (education level, specialisation, position, passout year,
joining date, certificates);
a DA can have several. Rows belong to the DA through the platform's
link_internal_record_id.
"""

from openg2p_registry_core.models import G2PRegister, G2PRegisterHistory
from openg2p_registry_core.models.g2p_intake_form import G2PIntakeForm
from sqlalchemy import Date, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from ..services import G2PRegisterDomainServiceQualification


class G2PQualification:
    education_level: Mapped[str] = mapped_column(String, nullable=True)  # DA_EDUCATION_LEVEL
    specialisation: Mapped[str] = mapped_column(String, nullable=True)  # DA_SPECIALISATION
    position: Mapped[str] = mapped_column(String, nullable=True)  # DA_POSITION
    joined_date: Mapped[str] = mapped_column(Date, nullable=True)
    passout_year: Mapped[int] = mapped_column(Integer, nullable=True)
    # Up to three files: [{"document_id": ..., "name": ...}], see the domain service.
    certificates: Mapped[list] = mapped_column(JSONB, nullable=True)


class G2PRegisterQualification(G2PRegister, G2PQualification):
    __tablename__ = "g2p_register_qualifications"

    def get_search_text_fields(self) -> str:
        return G2PRegisterDomainServiceQualification().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        return G2PRegisterDomainServiceQualification().construct_record_name(self.to_dict())


class G2PRegisterHistoryQualification(G2PRegisterHistory, G2PQualification):
    __tablename__ = "g2p_register_history_qualifications"


class G2PIntakeFormQualification(G2PIntakeForm, G2PRegister, G2PQualification):
    __tablename__ = "g2p_intake_form_qualifications"

    def get_search_text_fields(self) -> str:
        return G2PRegisterDomainServiceQualification().construct_search_text(self.to_dict())

    def get_record_name_fields(self) -> str:
        return G2PRegisterDomainServiceQualification().construct_record_name(self.to_dict())
