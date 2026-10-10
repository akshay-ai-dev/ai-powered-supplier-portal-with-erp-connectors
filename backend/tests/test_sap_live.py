# isort: off
from tests.test_api import login  # sets the test environment first
import pytest
from fastapi.testclient import TestClient
from app.connectors import sap_live
from app.main import app
# isort: on

URL = "/api/erp-monitor/live/sap/purchase-orders"

SAP_ANSWER = {
    "d": {
        "results": [
            {
                "__metadata": {"uri": "..."},
                "CompanyCode": "1710",
                "PurchaseOrder": "4500000001",
                "Supplier": "17300001",
                "PurchaseOrderDate": "/Date(1540771200000)/",
                "Language": "",
                "to_PurchaseOrderItem": {"__deferred": {}},
            }
        ]
    }
}


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def sandbox(monkeypatch):
    """Sandbox mode with a fake SAP that records each call instead of going online."""
    calls = []
    monkeypatch.setenv("SAP_MODE", "sandbox")
    monkeypatch.setenv("SAP_API_HUB_KEY", "test-key")
    monkeypatch.delenv("SAP_API_HUB_URL", raising=False)
    monkeypatch.setattr(
        sap_live, "_get", lambda url, headers: calls.append((url, headers)) or SAP_ANSWER
    )
    return calls


def test_buyer_and_admin_see_live_sap_rows(client, sandbox):
    for email in ("buyer@demo.com", "admin@demo.com"):
        r = client.get(URL, headers=login(client, email))
        assert r.status_code == 200, r.text
        assert r.json() == [
            {
                "PurchaseOrder": "4500000001",
                "Supplier": "17300001",
                "CompanyCode": "1710",
                "PurchaseOrderDate": "2018-10-29",
            }
        ]
    url, headers = sandbox[0]
    assert url.startswith(
        "https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder?"
    )
    assert headers["APIKey"] == "test-key"


def test_every_view_maps_to_a_read(client, sandbox):
    buyer = login(client, "buyer@demo.com")
    for view in sap_live.VIEWS:
        assert client.get(f"/api/erp-monitor/live/sap/{view}", headers=buyer).status_code == 200
    assert len(sandbox) == len(sap_live.VIEWS)
    assert client.get("/api/erp-monitor/live/sap/nonsense", headers=buyer).status_code == 404


def test_only_buyers_and_admins(client, sandbox):
    assert client.get(URL, headers=login(client, "inspector@demo.com")).status_code == 403
    assert client.get(URL, headers=login(client, "supplier@demo.com")).status_code in (401, 403)
    assert client.get(URL).status_code == 401
    assert sandbox == []


def test_clear_message_when_sap_is_not_set_up(client, monkeypatch):
    buyer = login(client, "buyer@demo.com")
    monkeypatch.delenv("SAP_MODE", raising=False)
    r = client.get(URL, headers=buyer)
    assert r.status_code == 503
    assert "SAP_MODE=sandbox" in r.json()["detail"]

    monkeypatch.setenv("SAP_MODE", "sandbox")
    monkeypatch.delenv("SAP_API_HUB_KEY", raising=False)
    r = client.get(URL, headers=buyer)
    assert r.status_code == 503
    assert "SAP_API_HUB_KEY" in r.json()["detail"]


def test_search_by_number(client, sandbox):
    buyer = login(client, "buyer@demo.com")
    r = client.get(URL, headers=buyer, params={"q": "4500000001"})
    assert r.status_code == 200, r.text
    url, _ = sandbox[0]
    assert "%24filter=PurchaseOrder+eq+%274500000001%27" in url
    # anything that is not a plain number is refused before SAP is called
    for bad in ("1' or '1'='1", "a b", "x" * 21):
        assert client.get(URL, headers=buyer, params={"q": bad}).status_code == 400
    assert len(sandbox) == 1


def test_real_mode_uses_the_company_sap_user(client, monkeypatch):
    calls = []
    monkeypatch.setenv("SAP_MODE", "real")
    monkeypatch.setenv("SAP_BASE_URL", "https://my-s4.example.com/")
    monkeypatch.setenv("SAP_CLIENT", "100")
    monkeypatch.setenv("SAP_USERNAME", "PORTAL_READ")
    monkeypatch.setenv("SAP_PASSWORD", "secret")
    monkeypatch.setattr(
        sap_live, "_get", lambda url, headers: calls.append((url, headers)) or SAP_ANSWER
    )
    r = client.get(URL, headers=login(client, "buyer@demo.com"))
    assert r.status_code == 200, r.text
    url, headers = calls[0]
    assert url.startswith(
        "https://my-s4.example.com/sap/opu/odata/sap/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder?"
    )
    assert headers["Authorization"] == "Basic UE9SVEFMX1JFQUQ6c2VjcmV0"
    assert headers["sap-client"] == "100"
    assert "APIKey" not in headers
