"""Approval workflow of unattended DA submissions: the service token is used
only when no signed-in user is behind the submission, and nothing is approved
automatically. Imports the extension, so it runs in the container."""

import asyncio
from types import SimpleNamespace
from unittest import mock

import pytest

from openg2p_registry_da_extension.register_domain.services import import_approval_workflow as m
from openg2p_registry_da_extension.register_domain.services.awe_service_token import ServiceTokenUnavailable


class TestUnattended:
    def test_file_import_and_partner_ingestion_qualify(self):
        assert m.is_unattended(SimpleNamespace(submission_source="PARTNER"), None)
        assert m.is_unattended(SimpleNamespace(submission_source="partner"), "  ")

    def test_web_intake_keeps_its_own_token(self):
        assert not m.is_unattended(SimpleNamespace(submission_source="STAFF_PORTAL"), None)
        assert not m.is_unattended(SimpleNamespace(submission_source="STAFF_PORTAL"), "tok")

    def test_a_user_token_means_a_person_is_behind_it(self):
        assert not m.is_unattended(SimpleNamespace(submission_source="PARTNER"), "tok")


def test_there_is_no_automatic_approval_left():
    assert not hasattr(m, "auto_approve_enabled")
    assert not hasattr(m, "auto_approve_if_unique")


def _start(token_result, source="PARTNER", bearer=None, is_da=True, enabled=True, opens_request=True):
    seen = {}

    async def platform_start(self, session, submission, *args, **kwargs):
        seen["bearer_token"] = kwargs.get("bearer_token")
        if opens_request:
            submission.awe_request_id = "req-1"
        return "started"

    service = m.DAAweIntegrationService.__new__(m.DAAweIntegrationService)
    submission = SimpleNamespace(submission_id="s-1", register_id="r-1", submission_source=source, awe_request_id=None)
    token_patch = mock.patch.object(m, "get_service_token", token_result)
    da_patch = mock.patch.object(m, "_is_da_register", mock.AsyncMock(return_value=is_da))
    base_patch = mock.patch.object(m.G2PAweIntegrationService, "start_intake_submission_workflow", platform_start)
    enabled_patch = mock.patch.object(m.DAAweIntegrationService, "_awe_enabled", lambda self: enabled)
    with token_patch, da_patch, base_patch, enabled_patch:
        result = asyncio.run(service.start_intake_submission_workflow(
            object(), submission, bearer_token=bearer, requester="x"))
    return result, seen


def test_an_import_starts_the_workflow_with_the_service_token():
    result, seen = _start(mock.AsyncMock(return_value="service-token"))
    assert result == "started"
    assert seen["bearer_token"] == "service-token"


def test_a_web_submission_keeps_the_user_token():
    token = mock.AsyncMock(return_value="service-token")
    _, seen = _start(token, source="STAFF_PORTAL", bearer="user-token")
    assert seen["bearer_token"] == "user-token"
    token.assert_not_called()


def test_a_missing_service_token_fails_the_row_with_a_clear_message():
    with pytest.raises(RuntimeError, match="The approval could not be started: no client secret"):
        _start(mock.AsyncMock(side_effect=ServiceTokenUnavailable("no client secret")))


def test_an_import_is_refused_when_approval_is_switched_off_in_the_process(caplog):
    token = mock.AsyncMock(return_value="service-token")
    with pytest.raises(RuntimeError, match="approval is switched off for imports") as exc:
        _start(token, enabled=False)
    token.assert_not_called()
    assert "AWE_" not in str(exc.value)  # setting names go to the log, not to the staff-facing row
    assert "AWE_ENABLED" in caplog.text


def test_an_import_is_refused_when_no_approval_request_was_opened():
    with pytest.raises(RuntimeError, match="no approval request was opened"):
        _start(mock.AsyncMock(return_value="service-token"), opens_request=False)


def test_a_web_submission_is_not_held_to_that_check():
    result, _ = _start(mock.AsyncMock(return_value="x"), source="STAFF_PORTAL", bearer="user-token",
                       enabled=False, opens_request=False)
    assert result == "started"
