from openg2p_fastapi_common.service import BaseService
from openg2p_registry_core.interfaces import G2PIdGeneratorInterface, IdAffix
from openg2p_registry_core.models.g2p_register import G2PRegister


class G2PIdGeneratorService(BaseService, G2PIdGeneratorInterface):
    """Prefix/suffix for functional IDs. The numeric part comes from the ID
    generator pool of the same name (docker/local-dev/id-generator.yaml and
    registry.idgenerator in the Helm values)."""

    def generate_prefix_suffix(self, g2p_register: G2PRegister, register_mnemonic: str) -> IdAffix:
        mnemonic = (register_mnemonic or "").lower()

        if mnemonic == "da":
            return IdAffix(prefix="DA-", suffix="")

        return IdAffix(prefix="DEFAULT-", suffix="")
