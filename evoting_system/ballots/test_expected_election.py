"""
FR-V-04 / FR-A-03: cast_ballot(..., expected_election_id=...) rejects a candidate from any election other than
the one the voting view validated, before any ballot, participation or audit row is written and without
consuming the voting token. Previously the BallotForm was the only layer restricting candidates to the
validated election (cast_ballot takes the election from the candidate).
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.utils import timezone

from auditlog.models import AuditLog
from ballots import views as ballot_views
from ballots.models import Ballot
from ballots.services import BallotCastError, cast_ballot
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter, VoterElectionParticipation


def _open(title):
    now = timezone.now()
    e = Election.objects.create(title=title, start_date=now, end_date=now + timedelta(hours=2))
    c = Candidate.objects.create(election=e, name=f"{title} Candidate")
    e.open_voting()
    return e, c


def _voter_session(nid="80100001"):
    v = Voter.objects.create(national_id_hash=sha256_hex(nid), full_name="Guard Voter", phone_number="+2548" + nid)
    return v, issue_session(v)


@pytest.mark.django_db
def test_fr_v04_expected_election_matching_candidate_is_accepted():
    election_a, cand_a = _open("Guard A")
    _, session = _voter_session()
    result = cast_ballot(uuid_token=str(session.uuid_token), candidate_id=cand_a.candidate_id,
                         expected_election_id=election_a.election_id)
    assert result.ballot.election_id == election_a.election_id


@pytest.mark.django_db
def test_fr_v04_expected_election_mismatch_is_rejected_and_writes_nothing():
    election_a, cand_a = _open("Guard A")
    election_b, cand_b = _open("Guard B")
    voter, session = _voter_session()

    with pytest.raises(BallotCastError, match="^Selected candidate does not exist\\.$"):
        cast_ballot(uuid_token=str(session.uuid_token), candidate_id=cand_b.candidate_id,
                    expected_election_id=election_a.election_id)

    assert Ballot.objects.count() == 0
    assert AuditLog.objects.count() == 0
    assert not VoterElectionParticipation.objects.filter(voter=voter).exists()
    assert Session.objects.get(pk=session.pk).is_active is True  # token not consumed

    # the same token still works for the validated election
    result = cast_ballot(uuid_token=str(session.uuid_token), candidate_id=cand_a.candidate_id,
                         expected_election_id=election_a.election_id)
    assert result.ballot.election_id == election_a.election_id


@pytest.mark.django_db
def test_fr_v04_expected_election_none_keeps_previous_behaviour():
    _open("Guard A")
    election_b, cand_b = _open("Guard B")
    _, session = _voter_session()
    result = cast_ballot(uuid_token=str(session.uuid_token), candidate_id=cand_b.candidate_id)
    assert result.ballot.election_id == election_b.election_id


@pytest.mark.django_db
def test_fr_v04_cast_view_passes_the_validated_election(client):
    election_a, cand_a = _open("Guard A")
    _open("Guard B")
    _, session = _voter_session()
    browser = client.session
    browser[VOTING_TOKEN_SESSION_KEY] = str(session.uuid_token)
    browser.save()

    with mock.patch.object(ballot_views, "cast_ballot", wraps=cast_ballot) as spy:
        response = client.post("/ballots/cast/", {"election": str(election_a.election_id),
                                                  "candidate": str(cand_a.candidate_id)})
    assert response.status_code == 200
    assert "Your ballot has been recorded" in response.content.decode()
    assert spy.call_count == 1
    assert spy.call_args.kwargs["expected_election_id"] == election_a.election_id
