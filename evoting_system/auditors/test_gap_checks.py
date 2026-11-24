"""
Gap check after the Chapter 5 security run: the Auditor dashboard root
(/auditors/) with no session redirects to the staff login. The existing
test_dashboard_rejects_anonymous_user also accepts 403; this one requires
the redirect.
"""

import pytest


@pytest.mark.django_db
def test_fr_aud_dashboard_root_anonymous_redirects_to_login(client):
    response = client.get("/auditors/")
    assert response.status_code == 302
    assert response["Location"].startswith("/admin/login/")
