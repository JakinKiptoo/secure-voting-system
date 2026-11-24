"""
Gap checks after the Chapter 5 security run: rollback of the ballot
transaction, a candidate from another election, and a CLOSED (not just
DRAFT) election. Each test checks that nothing was written.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from auditlog.models import AuditLog
from ballots import services as ballot_services
from ballots.models import Ballot
from ballots.services import BallotCastError, cast_ballot
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter, VoterElectionParticipation

INVALID_CHOICE = "Select a valid choice. That choice is not one of the available choices."


def _open_election(title, candidate_name):
    now = timezone.now()
    election = Election.objects.create(title=title, start_date=now, end_date=now + timedelta(hours=2))
    candidate = Candidate.objects.create(election=election, name=candidate_name)
    election.open_voting()
    return election, candidate


def _voter_and_session(national_id):
    voter = Voter.objects.create(
        national_id_hash=sha256_hex(national_id), full_name="Gap Voter", phone_number="+254711" + national_id[-6:]
    )
    return voter, issue_session(voter)


@pytest.mark.django_db
def test_fr_v04_v07_cast_ballot_rolls_back_everything_if_audit_step_fails(monkeypatch):
    """The audit-hash step (step 3) raises after the Ballot row was
    inserted (step 2): the whole transaction must roll back."""
    election, candidate = _open_election("Rollback Election", "Rollback Candidate")
    voter, session = _voter_and_session("71000001")

    def boom(*args, **kwargs):
        raise RuntimeError("simulated failure while appending the audit hash")

    monkeypatch.setattr(ballot_services, "_compute_ballot_hash", boom)

    with pytest.raises(RuntimeError, match="simulated failure"):
        cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    assert Ballot.objects.count() == 0
    assert AuditLog.objects.count() == 0
    assert Session.objects.get(pk=session.pk).is_active is True
    voter.refresh_from_db()
    assert voter.has_voted is False
    assert not VoterElectionParticipation.objects.filter(voter=voter, has_voted=True).exists()


@pytest.mark.django_db
def test_fr_v04_candidate_of_another_election_is_rejected_by_cast_view(client):
    """Two OPEN elections. The voter submits election A with a candidate
    of election B: the ballot form rejects it and nothing is written."""
    election_a, _ = _open_election("Cross Election A", "Candidate A")
    _, candidate_b = _open_election("Cross Election B", "Candidate B")
    voter, session = _voter_and_session("71000002")
    browser = client.session
    browser[VOTING_TOKEN_SESSION_KEY] = str(session.uuid_token)
    browser.save()

    response = client.post(
        "/ballots/cast/",
        {"election": str(election_a.election_id), "candidate": str(candidate_b.candidate_id)},
    )

    assert response.status_code == 200
    assert INVALID_CHOICE in response.content.decode()
    assert Ballot.objects.count() == 0
    assert AuditLog.objects.count() == 0
    assert Session.objects.get(pk=session.pk).is_active is True
    assert client.session[VOTING_TOKEN_SESSION_KEY] == str(session.uuid_token)


@pytest.mark.django_db
def test_fr_a03_closed_election_rejects_ballot():
    election, candidate = _open_election("Closed Election", "Closed Candidate")
    election.close_voting()
    voter, session = _voter_and_session("71000003")

    with pytest.raises(BallotCastError, match="not currently open for voting"):
        cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    assert Ballot.objects.count() == 0
    assert AuditLog.objects.count() == 0
    assert Session.objects.get(pk=session.pk).is_active is True
