from datetime import timedelta

import pytest
from django.utils import timezone

from ballots.models import Ballot
from elections.models import Candidate, Election

from .models import AuditLog


@pytest.mark.django_db
def test_auditlog_creation():
    """
    Smoke test only (Sprint 1, updated after the AuditLog.ballot
    correction): confirms AuditLog can be created with the fields
    SCHEMA.md lists, including the required OneToOneField to Ballot.
    Does NOT test insert-only enforcement (FR-DB-01) -- that's a
    PostgreSQL role-level GRANT/REVOKE, not application code, and is
    out of Sprint 1 scope.
    """
    now = timezone.now()
    election = Election.objects.create(
        title="2027 Student Council Election",
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    candidate = Candidate.objects.create(election=election, name="Amina Yusuf")
    ballot = Ballot.objects.create(election=election, candidate=candidate)

    entry = AuditLog.objects.create(
        ballot=ballot,
        action_type="ballot_cast",
        ballot_hash="0" * 64,
        previous_hash="",
    )

    assert entry.log_id is not None
    assert entry.timestamp is not None
    assert entry.ballot == ballot
