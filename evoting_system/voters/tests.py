import pytest

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
