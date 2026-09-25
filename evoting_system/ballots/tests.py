from datetime import timedelta

import pytest
from django.utils import timezone

from elections.models import Candidate, Election

from .models import Ballot


@pytest.mark.django_db
def test_ballot_creation():
    """
    Smoke test only (Sprint 1): confirms Ballot can be created with
    Election/Candidate FKs and no Voter/Session FK exists on the
    model at all (the anonymisation invariant is structural -- see
    ballots/models.py docstring). Not real FR-V-04 coverage -- the
    atomic ballot-casting transaction is Sprint 3.
    """
    now = timezone.now()
    election = Election.objects.create(
        title="2027 Student Council Election",
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    candidate = Candidate.objects.create(election=election, name="Amina Yusuf")

    ballot = Ballot.objects.create(election=election, candidate=candidate)

    assert ballot.ballot_id is not None
    assert not hasattr(ballot, "voter")
    assert not hasattr(ballot, "session")
