import pytest
from django.urls import reverse

from voter_sessions.models import Session

from . import views as voters_views
from .crypto_utils import sha256_hex
from .models import Voter


@pytest.mark.django_db
def test_fr_v00_voter_creation():
    """
    Smoke test only (Sprint 1): confirms the Voter model can be
    created and persisted with the fields SCHEMA.md specifies. Not
    real FR-V-00 coverage (uniqueness validation, registration flow) --
    that lands with the Sprint 2 registration view.
    """
    voter = Voter.objects.create(
        national_id_hash="hashed-national-id",
        full_name="Jane Wanjiru",
        phone_number="+254700000000",
    )

    assert voter.voter_id is not None
    assert voter.has_voted is False
    assert voter.registration_date is not None


@pytest.mark.django_db
def test_fr_v00_registration_view_creates_voter_and_rejects_duplicate(client):
    """FR-V-00: registration view creates a Voter, and rejects a duplicate National ID."""
    url = reverse("voters:register")
    payload = {
        "national_id": "12345678",
        "full_name": "Grace Achieng",
        "phone_number": "+254722000000",
    }

    response = client.post(url, payload)
    assert response.status_code == 200
    assert Voter.objects.count() == 1

    duplicate_response = client.post(url, payload)
    assert duplicate_response.status_code == 200
    assert Voter.objects.count() == 1
    assert "already registered" in duplicate_response.content.decode().lower()


@pytest.mark.django_db
def test_fr_v02_credentials_view_rejects_already_voted(client):
    """FR-V-02: has_voted short-circuit rejects authentication before any OTP is requested."""
    Voter.objects.create(
        national_id_hash=sha256_hex("87654321"),
        full_name="Peter Kamau",
        phone_number="+254733000000",
        has_voted=True,
    )

    url = reverse("voters:credentials")
    response = client.post(url, {"national_id": "87654321", "phone_number": "+254733000000"})

    assert response.status_code == 200
    assert "already cast a ballot" in response.content.decode().lower()


@pytest.mark.django_db
def test_fr_v01_credentials_view_rejects_unknown_voter(client):
    """FR-V-01: credentials that match no Voter record are rejected."""
    url = reverse("voters:credentials")
    response = client.post(url, {"national_id": "00000000", "phone_number": "+254700000001"})

    assert response.status_code == 200
    assert "invalid credentials" in response.content.decode().lower()


@pytest.mark.django_db
def test_full_mfa_flow_issues_session_token(client, monkeypatch):
    """
    End-to-end: FR-V-01 credential match -> FR-V-02 has_voted check
    passes -> FR-G-01 stub OTP delivery -> FR-V-03 OTP match ->
    FR-S-01 session-bound UUID token issuance.

    Monkeypatches the stub SMS gateway to capture the OTP it would
    have "delivered", since the real flow never returns it over HTTP.
    """
    captured = {}

    def fake_send_otp(phone_number, otp):
        captured["otp"] = otp
        return True

    monkeypatch.setattr(voters_views.sms_gateway, "send_otp", fake_send_otp)

    voter = Voter.objects.create(
        national_id_hash=sha256_hex("11223344"),
        full_name="Wanjiku Mwangi",
        phone_number="+254744000000",
    )

    creds_response = client.post(
        reverse("voters:credentials"),
        {"national_id": "11223344", "phone_number": "+254744000000"},
    )
    assert creds_response.status_code == 302
    assert "otp" in captured

    otp_response = client.post(reverse("voters:verify_otp"), {"otp": captured["otp"]})
    assert otp_response.status_code == 200
    assert "session established" in otp_response.content.decode().lower()

    session = Session.objects.get(voter=voter)
    assert session.uuid_token is not None
    assert session.is_active is True

    voter.refresh_from_db()
    assert voter.otp_hash == ""  # single-use: cleared after successful match


@pytest.mark.django_db
def test_fr_v03_verify_otp_view_rejects_incorrect_otp(client, monkeypatch):
    """FR-V-03: an incorrect OTP is rejected and no session token is issued."""
    monkeypatch.setattr(voters_views.sms_gateway, "send_otp", lambda phone_number, otp: True)

    voter = Voter.objects.create(
        national_id_hash=sha256_hex("55667788"),
        full_name="Otieno Odhiambo",
        phone_number="+254755000000",
    )

    client.post(
        reverse("voters:credentials"),
        {"national_id": "55667788", "phone_number": "+254755000000"},
    )
    response = client.post(reverse("voters:verify_otp"), {"otp": "000000"})

    assert response.status_code == 200
    assert "incorrect otp" in response.content.decode().lower()
    assert not Session.objects.filter(voter=voter).exists()
