from datetime import timedelta

import pytest
from django.utils import timezone

from .models import Candidate, Election


@pytest.mark.django_db
def test_fr_a01_election_creation():
    """Smoke test only: confirms Election can be created (FR-A-01)."""
    now = timezone.now()
    election = Election.objects.create(
        title="2027 Student Council Election",
        start_date=now,
        end_date=now + timedelta(days=1),
    )

    assert election.election_id is not None
    assert election.status == Election.Status.DRAFT


@pytest.mark.django_db
def test_fr_a02_candidate_creation():
    """Smoke test only: confirms Candidate can be created against an Election (FR-A-02)."""
    now = timezone.now()
    election = Election.objects.create(
        title="2027 Student Council Election",
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    candidate = Candidate.objects.create(
        election=election,
        name="Amina Yusuf",
        party="Independent",
        biography="Third-year student.",
    )

    assert candidate.candidate_id is not None
    assert candidate.election == election
