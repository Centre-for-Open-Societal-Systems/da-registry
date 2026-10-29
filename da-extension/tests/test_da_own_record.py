"""A Development Agent's own record: token inspection, the synthetic data policy
and the change-request check (pure functions; the DB lookup is not exercised)."""

import base64
import json

import pytest

from openg2p_registry_da_extension.register_domain.services import da_own_record as m

CLIENT = "da-registry-staff-portal"


def token(claims: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    return f"eyJhbGciOiJub25lIn0.{body}.sig"


def roles_token(roles, da_id="DA-1234567890", client=CLIENT):
    claims = {"preferred_username": "x", "resource_access": {client: {"roles": roles}}}
    if da_id:
        claims["da_id"] = da_id
    return token(claims)


class TestSelfServiceDaId:
    def test_data_editor_with_claim_is_restricted(self):
        assert m.self_service_da_id(roles_token(["Data Editor"])) == "DA-1234567890"

    def test_data_policy_roles_do_not_widen(self):
        assert m.self_service_da_id(roles_token(["Data Editor", "DP_DA_WOREDA_ET010101"])) == "DA-1234567890"

    @pytest.mark.parametrize("wider", ["Intake Officer", "Data Validator", "Operations Administrator", "Technical Administrator"])
    def test_any_wider_role_is_not_restricted(self, wider):
        assert m.self_service_da_id(roles_token(["Data Editor", wider])) is None

    def test_no_claim_is_not_restricted(self):
        assert m.self_service_da_id(roles_token(["Data Editor"], da_id=None)) is None

    def test_roles_on_another_client_are_ignored(self):
        # roles only on a different client: nothing wider on the registry client
        assert m.self_service_da_id(roles_token(["Operations Administrator"], client="farmer-registry-staff-portal")) == "DA-1234567890"

    @pytest.mark.parametrize("bad", [None, "", "not-a-jwt", "a.b"])
    def test_garbage_token_is_ignored(self, bad):
        assert m.self_service_da_id(bad) is None

    def test_claim_name_is_configurable(self, monkeypatch):
        monkeypatch.setenv("DA_SELF_SERVICE_CLAIM", "agent_id")
        t = token({"agent_id": "DA-0000000001", "resource_access": {CLIENT: {"roles": ["Data Editor"]}}})
        assert m.self_service_da_id(t) == "DA-0000000001"


class TestSelfPolicy:
    def test_policy_restricts_the_da_register_to_one_functional_id(self):
        p = m.self_policy("reg-1", "DA-1234567890")
        assert p["register_id"] == "reg-1"
        assert p["policy_target"] == "REGISTER_RECORD" and p["policy_type"] == "ALLOW"
        cond = p["policy_filter_expression"]["children"][0]
        assert cond == {"type": "CONDITION", "field_id": "functional_record_id", "operator": "eq", "value": "DA-1234567890"}


class _Payload:
    def __init__(self, section_id, internal_record_id, change_payload=None):
        self.section_id = section_id
        self.internal_record_id = internal_record_id
        self.change_payload = change_payload or [{"internal_record_id": internal_record_id}]


class TestChangeRequestCheck:
    @pytest.mark.asyncio
    async def test_identity_section_is_refused_before_any_lookup(self):
        with pytest.raises(Exception) as exc:
            await m.check_own_change_request(_Payload("da_identity_section_01", "rid"), "DA-1")
        assert "contact, service and location" in str(exc.value.message if hasattr(exc.value, "message") else exc.value)

    @pytest.mark.asyncio
    async def test_two_different_records_in_one_request_are_refused(self):
        payload = _Payload("da_contact_section_04", "rid-a", [{"internal_record_id": "rid-b"}])
        with pytest.raises(Exception) as exc:
            await m.check_own_change_request(payload, "DA-1")
        assert "own record" in str(exc.value.message if hasattr(exc.value, "message") else exc.value)

    def test_editable_sections(self):
        assert m.EDITABLE_SECTIONS == {"da_contact_section_04", "da_service_section_02", "da_location_section_03"}


class TestChangeRequestService:
    def test_it_is_registered_ahead_of_the_platform_controller_service(self):
        from openg2p_registry_core.controller_services import G2PRegisterChangerequestControllerService

        pytest.importorskip("iam_core")
        m.install_da_own_record_guard()
        service = G2PRegisterChangerequestControllerService.get_component()
        assert isinstance(service, m.DAOwnRecordChangeRequestControllerService)

    def test_a_change_to_another_record_is_refused_before_the_platform_is_called(self):
        import asyncio
        from types import SimpleNamespace
        from unittest import mock

        service = m.DAOwnRecordChangeRequestControllerService()
        payload = SimpleNamespace(section_id="da_identity_section_01", internal_record_id="r-1", change_payload=[])
        request = SimpleNamespace(request_body=SimpleNamespace(request_payload=payload))
        with mock.patch.object(m.G2PRegisterChangerequestControllerService, "create_change_request", mock.AsyncMock()) as platform:
            with pytest.raises(Exception, match="contact, service and location"):
                asyncio.run(service.create_change_request(request, bearer_token=roles_token(["Data Editor"])))
        platform.assert_not_called()

    def test_a_user_without_the_claim_goes_straight_to_the_platform(self):
        import asyncio
        from types import SimpleNamespace
        from unittest import mock

        service = m.DAOwnRecordChangeRequestControllerService()
        request = SimpleNamespace(request_body=SimpleNamespace(request_payload=SimpleNamespace()))
        with mock.patch.object(m.G2PRegisterChangerequestControllerService, "create_change_request", mock.AsyncMock(return_value="created")) as platform:
            result = asyncio.run(service.create_change_request(request, bearer_token=roles_token(["Data Editor"], da_id=None)))
        assert result == "created"
        platform.assert_called_once()
