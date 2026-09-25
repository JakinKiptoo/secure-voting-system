import uuid
from datetime import timedelta

import pytest
from django.utils import timezone

from voters.models import Voter

from .models import Session


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
