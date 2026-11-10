import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from voters.models import Voter

from .models import Session
from .services import SESSION_TOKEN_LIFETIME_MINUTES, issue_session


@pytest.mark.django_db
def test_fr_s01_issue_session_creates_single_use_token_bound_to_voter():
    """
    Sprint 5 gap fill: direct unit coverage of
    voter_sessions/services.py::issue_session() itself -- the actual
    FR-S-01 behaviour ("on successful MFA, issue a single-use,
    session-bound UUID token identifying the session without
    identifying the Voter"). Until now FR-S-01 was only exercised
    indirectly through voters/tests.py's full MFA-flow integration
    test; this isolates the service function so a regression in it
    specifically (not the view around it) fails here.
    """
    voter = Voter.objects.create(
        national_id_hash="fr-s01-direct-test-hash",
        full_name="Wanjiru Kamau",
        phone_number="+254722000111",
    )

    before = timezone.now()
    session = issue_session(voter)
    after = timezone.now()

    assert session.voter == voter
    assert session.is_active is True
    # Single-use: a fresh, unique UUID token every call -- not derived
    # from the voter's own identity in any way.
    assert isinstance(session.uuid_token, uuid.UUID)
    other_session = issue_session(voter)
    assert other_session.uuid_token != session.uuid_token

    expected_earliest = before + timedelta(minutes=SESSION_TOKEN_LIFETIME_MINUTES)
    expected_latest = after + timedelta(minutes=SESSION_TOKEN_LIFETIME_MINUTES)
    assert expected_earliest <= session.expiry_time <= expected_latest


@pytest.mark.django_db
def test_fr_s01_session_creation():
    """
    Smoke test only (Sprint 1): confirms the Session model can be
    created with a Voter FK and a unique uuid_token. Not real FR-S-01
    coverage -- token issuance-on-MFA-success is Sprint 2 behaviour.
    """
    voter = Voter.objects.create(
        national_id_hash="hashed-national-id",
        full_name="John Otieno",
        phone_number="+254711111111",
    )

    session = Session.objects.create(
        voter=voter,
        uuid_token=uuid.uuid4(),
        expiry_time=timezone.now() + timedelta(minutes=15),
    )

    assert session.session_id is not None
    assert session.is_active is True
    assert session.voter == voter
