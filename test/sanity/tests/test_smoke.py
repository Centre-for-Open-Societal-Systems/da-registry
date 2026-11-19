import pytest

# Liveness + wiring for the DA Registry partner-api (the PEP). No auth, no
# data created — runs on every install/upgrade.
#
# Overlays the platform suite's test_smoke.py: the rc.614 partner-api serves the
# DCI search as /dci/sync/search and /dci/async/search, while the platform's
# copy of this test still looks for the retired /dci/registry prefix and fails
# every install. The assertion below names the routes the API actually has.


@pytest.mark.smoke
def test_partner_ping(partner_client):
    r = partner_client.get("/ping")
    assert r.status_code == 200, r.text


@pytest.mark.smoke
def test_openapi_has_dci_search(partner_client):
    r = partner_client.get("/openapi.json")
    assert r.status_code == 200, r.text
    paths = r.json().get("paths", {})
    missing = [route for route in ("/dci/sync/search", "/dci/async/search") if route not in paths]
    assert not missing, f"DCI search routes {missing} not found in openapi paths: {sorted(paths)[:20]}"
