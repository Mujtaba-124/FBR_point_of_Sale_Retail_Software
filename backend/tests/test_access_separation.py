"""Super Admin and Company Workspace isolation, enforced by the backend."""

import pytest

from app.models import AccessCategory
from tests.conftest import login

# Company accounts sign in here, which requires a valid subscription.
pytestmark = pytest.mark.usefixtures("valid_subscription")

SUPER = "/api/v1/super-admin/workspace"
COMPANY = "/api/v1/company/workspace"
COMPANY_ADMIN = "/api/v1/company/admin/workspace"
PROTECTED = ["/api/v1/auth/me", SUPER, COMPANY, COMPANY_ADMIN]

# category -> {endpoint: expected status}
MATRIX = {
    AccessCategory.SUPER_ADMIN: {SUPER: 200, COMPANY: 403, COMPANY_ADMIN: 403},
    AccessCategory.COMPANY_ADMIN: {SUPER: 403, COMPANY: 200, COMPANY_ADMIN: 200},
    AccessCategory.COMPANY_USER: {SUPER: 403, COMPANY: 200, COMPANY_ADMIN: 403},
}


@pytest.mark.parametrize("path", PROTECTED)
def test_unauthenticated_requests_get_401(client, path):
    response = client.get(path)
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"


@pytest.mark.parametrize("path", PROTECTED)
def test_forged_session_cookie_gets_401(client, path):
    client.cookies.set("__Host-cheena_session", "not-a-real-token")
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("category", list(MATRIX))
def test_access_matrix(client, make_user, category):
    email, password = make_user(category)
    assert login(client, email, password).status_code == 200

    for path, expected in MATRIX[category].items():
        response = client.get(path)
        assert response.status_code == expected, (category, path)
        if expected == 403:
            assert response.json()["error"]["code"] == "permission_denied"
        else:
            assert response.json()["user"]["email"] == email


def test_super_admin_is_blocked_from_company_apis(client, make_user):
    email, password = make_user(AccessCategory.SUPER_ADMIN)
    login(client, email, password)
    assert client.get(COMPANY).status_code == 403
    assert client.get(COMPANY_ADMIN).status_code == 403


def test_company_admin_is_blocked_from_super_admin_apis(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_ADMIN)
    login(client, email, password)
    assert client.get(SUPER).status_code == 403


def test_company_user_is_blocked_from_admin_routes(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_USER)
    login(client, email, password)
    assert client.get(COMPANY_ADMIN).status_code == 403
    assert client.get(SUPER).status_code == 403


def test_role_headers_from_the_client_are_ignored(client, make_user):
    email, password = make_user(AccessCategory.COMPANY_USER)
    login(client, email, password)
    spoof = {"X-Access-Category": "super_admin", "X-Role": "super_admin"}
    assert client.get(SUPER, headers=spoof).status_code == 403
    assert client.get("/api/v1/auth/me").json()["access_category"] == "company_user"
