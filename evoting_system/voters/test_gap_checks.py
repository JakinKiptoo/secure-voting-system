"""
Gap check after the Chapter 5 security run (NFR-SE-01): an over-long
National ID containing HTML special characters is re-rendered escaped
on the login page, never raw.
"""

import pytest
from django.utils.html import escape

PAYLOAD = "\"><script>alert('evs')</script><img src=x onerror=alert(1)>&" + "9" * 40


@pytest.mark.django_db
def test_nfr_se01_login_national_id_payload_is_reflected_escaped(client):
    assert len(PAYLOAD) > 64

    response = client.post("/voters/login/", {"national_id": PAYLOAD, "phone_number": "+254700000999"})
    body = response.content.decode()

    assert response.status_code == 200  # form re-rendered, not accepted
    assert "at most 64 characters" in body
    assert PAYLOAD not in body
    assert "<script>alert('evs')</script>" not in body
    assert escape(PAYLOAD) in body
