"""
FR-EL-05 (Per-Election Participation Tracking) tests.

Covers the three things the FR-EL-05 prompt explicitly asked for:
  (a) a voter who voted in Election A can still authenticate and cast
      a ballot in Election B
  (b) a voter cannot vote twice in the SAME election (must still work
      exactly as before)
  (c) the anonymity invariant still holds -- VoterElectionParticipation
      has no path, direct or indirect, to Candidate or Ballot's choice
      data -- verified the same way Thread A's leak tests did (cast a
      real ballot with distinctive values first, then check for their
      absence), not just asserted from the schema.

File named test_fr_el_05.py (matches pytest.ini's "test_*.py" pattern)
rather than folded into voters/tests.py or ballots/tests.py, since this
feature spans both apps (voters/models.py + voters/views.py +
ballots/services.py) and deserves its own clearly-labelled home for
Chapter 5 traceability.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from ballots.models import Ballot
from ballots.services import BallotCastError, cast_ballot
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter, VoterElectionParticipation


def _make_election(title, open_it=True):
    now = timezone.now()
    election = Election.objects.create(title=title, start_date=now, end_date=now + timedelta(hours=2))
    candidate = Candidate.objects.create(election=election, name=f"Candidate for {title}")
    if open_it:
        election.open_voting()
    return election, candidate


def _make_voter(suffix):
    return Voter.objects.create(
        national_id_hash=sha256_hex(f"5000000{suffix}"),
        full_name=f"FR-EL-05 Voter {suffix}",
        phone_number=f"+25470000000{suffix}",
    )


# ---------------------------------------------------------------------
# (a) voting in Election A does not lock a voter out of Election B
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_voter_who_voted_in_election_a_can_still_authenticate_for_election_b(client):
    """
    Full authentication flow (not just cast_ballot() directly): voter
    votes in Election A, A closes, B opens, and the SAME voter can
    authenticate (FR-V-01/02/03) all over again for B -- proving the
    rescoped FR-V-02 check (voters/eligibility.py) actually works
    through credentials_view(), not just at the service layer.
    """
    election_a, candidate_a = _make_election("Election A")
    voter = _make_voter("1")

    session_a = issue_session(voter)
    cast_ballot(uuid_token=str(session_a.uuid_token), candidate_id=candidate_a.candidate_id)

    election_a.close_voting()
    election_b, candidate_b = _make_election("Election B")

    # Re-authenticate for Election B via the real view, exactly as a
    # returning voter would.
    creds_url = reverse("voters:credentials")
    response = client.post(
        creds_url,
        {
            "national_id": "50000001",
            "phone_number": "+254700000001",
        },
    )
    assert response.status_code == 302, (
        "voter who already voted in (now-closed) Election A was wrongly "
        "rejected from authenticating for Election B"
    )
    assert response.url == reverse("voters:verify_otp")


@pytest.mark.django_db
def test_voter_who_voted_in_election_a_can_cast_a_ballot_in_election_b():
    """Same scenario as above, but all the way through to a second,
    successful cast_ballot() call for Election B."""
    election_a, candidate_a = _make_election("Election A Cast")
    voter = _make_voter("2")

    session_a = issue_session(voter)
    result_a = cast_ballot(uuid_token=str(session_a.uuid_token), candidate_id=candidate_a.candidate_id)
    assert result_a.ballot.election_id == election_a.election_id

    election_a.close_voting()
    election_b, candidate_b = _make_election("Election B Cast")

    session_b = issue_session(voter)
    result_b = cast_ballot(uuid_token=str(session_b.uuid_token), candidate_id=candidate_b.candidate_id)
    assert result_b.ballot.election_id == election_b.election_id

    # Both participation rows exist, both correctly marked voted,
    # scoped to their own election.
    participations = VoterElectionParticipation.objects.filter(voter=voter).order_by("election__title")
    assert participations.count() == 2
    assert all(p.has_voted for p in participations)
    assert {p.election_id for p in participations} == {election_a.election_id, election_b.election_id}


# ---------------------------------------------------------------------
# (b) same-election double-vote is still blocked
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_voter_cannot_vote_twice_in_the_same_election_via_two_sessions():
    """
    Reproduces exactly the race the original Sprint 3 defensive check
    guarded against (Sprint 2 doesn't invalidate a voter's other
    active sessions on a new login): two valid, active Sessions for
    the SAME voter, both pointed at the SAME election. The first
    cast_ballot() succeeds; the second must be rejected by the
    per-election VoterElectionParticipation check, not merely by the
    (now-legacy, non-gating) Voter.has_voted flag.
    """
    election, candidate = _make_election("Same Election Double Vote")
    voter = _make_voter("3")

    session_1 = issue_session(voter)
    session_2 = issue_session(voter)  # second concurrent valid session

    cast_ballot(uuid_token=str(session_1.uuid_token), candidate_id=candidate.candidate_id)

    with pytest.raises(BallotCastError, match="already cast a ballot in this election"):
        cast_ballot(uuid_token=str(session_2.uuid_token), candidate_id=candidate.candidate_id)

    assert Ballot.objects.filter(election=election).count() == 1
    assert VoterElectionParticipation.objects.get(voter=voter, election=election).has_voted is True


@pytest.mark.django_db
def test_credentials_view_rejects_reauth_attempt_for_same_still_open_election(client):
    """The authentication-side mirror of the above: once voted in the
    (still open) election, a fresh login attempt for that SAME
    election is rejected by the rescoped FR-V-02 check."""
    election, candidate = _make_election("Same Election Reauth")
    voter = _make_voter("4")

    session = issue_session(voter)
    cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    response = client.post(
        reverse("voters:credentials"),
        {"national_id": "50000004", "phone_number": "+254700000004"},
    )
    assert response.status_code == 200
    assert "already cast a ballot" in response.content.decode().lower()


# ---------------------------------------------------------------------
# (c) anonymity invariant: VoterElectionParticipation never leaks
# which candidate a voter chose, directly or indirectly.
# ---------------------------------------------------------------------


def test_voterelectionparticipation_has_no_candidate_or_ballot_field():
    """
    Structural check: the model's only foreign keys are to Voter and
    Election -- never Candidate or Ballot, directly or via any other
    field. No django_db needed; this only inspects the model class.
    """
    field_names = {f.name for f in VoterElectionParticipation._meta.get_fields()}
    assert field_names == {"id", "voter", "election", "has_voted", "voted_at"}

    related_model_names = {
        f.related_model.__name__
        for f in VoterElectionParticipation._meta.get_fields()
        if f.is_relation and f.related_model is not None
    }
    assert related_model_names == {"Voter", "Election"}
    assert "Candidate" not in related_model_names
    assert "Ballot" not in related_model_names


@pytest.mark.django_db
def test_candidate_and_ballot_have_no_reverse_relation_to_participation():
    """
    The other direction of the same guarantee: Candidate and Ballot
    must not gain a reverse accessor back to VoterElectionParticipation
    either (which would be just as bad a leak path as a forward FK).
    """
    candidate_related_names = {
        f.name for f in Candidate._meta.get_fields() if f.is_relation
    }
    ballot_related_names = {f.name for f in Ballot._meta.get_fields() if f.is_relation}

    assert "voterelectionparticipation" not in candidate_related_names
    assert "voterelectionparticipation" not in ballot_related_names


@pytest.mark.django_db
def test_participation_data_never_contains_the_voters_candidate_choice():
    """
    The actual leak test, modeled directly on Thread A's rigor: cast a
    REAL ballot for a distinctively-named candidate first (not an
    empty/synthetic participation row), then confirm that candidate's
    identifying data appears NOWHERE in the resulting
    VoterElectionParticipation row -- not in any field value, and not
    reachable via any attribute path starting from it.
    """
    now = timezone.now()
    election = Election.objects.create(
        title="Anonymity Check Election", start_date=now, end_date=now + timedelta(hours=1)
    )
    distinctive_candidate_name = "Zzyzx Nakamura-Odongo"
    candidate = Candidate.objects.create(
        election=election, name=distinctive_candidate_name, party="Distinctive Test Party"
    )
    election.open_voting()

    voter = _make_voter("5")
    session = issue_session(voter)
    result = cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)
    distinctive_ballot_id = str(result.ballot.ballot_id)
    distinctive_candidate_id = str(candidate.candidate_id)

    participation = VoterElectionParticipation.objects.get(voter=voter, election=election)

    # Every field VoterElectionParticipation actually has, stringified
    # -- none of them should be able to contain the candidate's name,
    # the candidate's own PK, or the ballot's PK, because the model
    # has no field through which any of those could ever get in.
    rendered_values = [
        str(participation.voter_id),
        str(participation.election_id),
        str(participation.has_voted),
        str(participation.voted_at),
    ]
    for value in rendered_values:
        assert distinctive_candidate_name not in value
        assert distinctive_candidate_id not in value
        assert distinctive_ballot_id not in value

    # And confirm there is no attribute path at all from the
    # participation row to Candidate or Ballot to even attempt such a
    # lookup through (the structural tests above already prove this at
    # the schema level; this re-confirms it against the actual live
    # instance this test just created).
    assert not hasattr(participation, "candidate")
    assert not hasattr(participation, "ballot")
