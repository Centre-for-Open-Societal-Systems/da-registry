from enum import Enum


class DASalutationEnum(str, Enum):
    MR = "MR"
    MRS = "MRS"
    DR = "DR"


class DAEducationLevelEnum(str, Enum):
    CERTIFICATE = "CERTIFICATE"
    DIPLOMA = "DIPLOMA"
    DEGREE = "DEGREE"
    MASTERS = "MASTERS"


class DAPositionEnum(str, Enum):
    """Provisional list (team: "confirmation required, keep suggested options")."""

    DEVELOPMENT_AGENT = "DEVELOPMENT_AGENT"
    SENIOR_DA = "SENIOR_DA"


class DASourceEnum(str, Enum):
    """How the DA record entered the registry."""

    WEB_INTAKE = "WEB_INTAKE"
    CSV_IMPORT = "CSV_IMPORT"

