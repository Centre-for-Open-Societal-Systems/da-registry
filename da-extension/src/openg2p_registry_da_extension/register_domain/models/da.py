from openg2p_registry_core.models import (
    G2PGeo,
    G2PGeoHistory,
    G2PPerson,
    G2PPersonHistory,
    G2PRegister,
    G2PRegisterHistory,
)
from openg2p_registry_core.models.g2p_intake_form import G2PIntakeForm
from sqlalchemy import Date, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from ..services import G2PRegisterDomainServiceDA


# Coded values (prefix, gender, marital status, qualification, specialisation,
# position, source) are Master Data codes; the lists live in the openg2p-data pack.
SOURCE_WEB_INTAKE = "WEB_INTAKE"


class G2PDA:
    """Development Agent profile (DA registry field list agreed with the team, Oct 2026).

    Columns inherited from the platform and used as-is:
      G2PPerson  prefix (Salutation), first_name (Name), middle_name (Father
                 Name), last_name (Grandfather Name), gender, marital_status,
                 education_level, foundational_id (Fayda ID)
      G2PGeo     geo_lowest_level_value_id, geo_code_hierarchy_json
                 (Region / Zone / Woreda / Kebele)
      G2PRegister functional_record_id (the DA-ID), record_name, search_text,
                 record_status, created_*/last_approved_*
    """

    # Month / Year of Birth in the Ethiopian calendar (month 1-13).
    birth_month_ec: Mapped[int] = mapped_column(Integer, nullable=True)
    birth_year_ec: Mapped[int] = mapped_column(Integer, nullable=True)

    # Contact details as flat columns (the list view and filters only support
    # plain getattr() lookups, not the platform's phone_numbers / emails JSON).
    mobile_number: Mapped[str] = mapped_column(String, nullable=True)
    telegram_number: Mapped[str] = mapped_column(String, nullable=True)
    alternate_number: Mapped[str] = mapped_column(String, nullable=True)
    email: Mapped[str] = mapped_column(String, nullable=True)

    specialisation: Mapped[str] = mapped_column(String, nullable=True)  # attribute lookup
    position: Mapped[str] = mapped_column(String, nullable=True)  # DA_POSITION code (Master Data)
    joined_date: Mapped[str] = mapped_column(Date, nullable=True)  # optional for now

    # A record that arrives without a source came in through the web intake
    # form; CSV import always sets CSV_IMPORT explicitly.
    source: Mapped[str] = mapped_column(
        String, nullable=True, default=SOURCE_WEB_INTAKE, server_default=SOURCE_WEB_INTAKE
    )

    # Record id and approver in DA Services, for records it sends after its own
    # approval (partner ingestion). Kept for tracing and audit.
    upstream_reference: Mapped[str] = mapped_column(String, nullable=True, index=True)
    upstream_approved_by: Mapped[str] = mapped_column(String, nullable=True)

    # Flattened out of geo_code_hierarchy_json for the list view and filters.
    region_name: Mapped[str] = mapped_column(String, nullable=True)
    zone_name: Mapped[str] = mapped_column(String, nullable=True)
    woreda_name: Mapped[str] = mapped_column(String, nullable=True)
    kebele_name: Mapped[str] = mapped_column(String, nullable=True)
    # Master Data codes of the same levels (OCHA P-codes, e.g. ET040301), which
    # DA Services filters and scopes on; see geo_codes.py.
    region_code: Mapped[str] = mapped_column(String, nullable=True, index=True)
    zone_code: Mapped[str] = mapped_column(String, nullable=True, index=True)
    woreda_code: Mapped[str] = mapped_column(String, nullable=True, index=True)


# All Register classes should have the prefix G2PRegister
class G2PRegisterDA(G2PRegister, G2PPerson, G2PGeo, G2PDA):
    __tablename__ = "g2p_register_das"

    def get_record_name_fields(self) -> str:
        return G2PRegisterDomainServiceDA().construct_record_name(self.to_dict())

    def get_search_text_fields(self) -> str:
        return G2PRegisterDomainServiceDA().construct_search_text(self.to_dict())


# All Register History classes should have the prefix G2PRegisterHistory
class G2PRegisterHistoryDA(G2PRegisterHistory, G2PPersonHistory, G2PGeoHistory, G2PDA):
    __tablename__ = "g2p_register_history_das"


# All Intake Form classes should have the prefix G2PIntakeForm
class G2PIntakeFormDA(G2PIntakeForm, G2PRegister, G2PPerson, G2PGeo, G2PDA):
    __tablename__ = "g2p_intake_form_das"

    def get_record_name_fields(self) -> str:
        return G2PRegisterDomainServiceDA().construct_record_name(self.to_dict())

    def get_search_text_fields(self) -> str:
        return G2PRegisterDomainServiceDA().construct_search_text(self.to_dict())
