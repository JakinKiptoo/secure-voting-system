"""
FR-EL-06 investigation (Phase 1 only -- see handover). Not a standing
regression test of a fix (none has been built yet); this is the
single exploratory test the FR-EL-06 prompt asked for, to observe
actual behavior when two Elections are OPEN at once, since nothing in
the code currently prevents that state and it had never been
exercised before.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from elections.models import Candidate, Election
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

from .forms import BallotForm
from .services import cast_ballot


@pytest.mark.django_db
def test_two_elections_can_be_open_simultaneously_and_voting_is_scoped_correctly(client):
    """
    1. Opens TWO elections at once via open_voting() directly (proving
       nothing blocks this at the model layer).
    2. Confirms cast_ballot_view's `Election.objects.filter(status=OPEN).first()`
       does not crash (it uses .first(), not .get()) and confirms which
       election's candidates it actually shows in the ballot form.
    3. Casts a real ballot via cast_ballot() for a candidate belonging
       to the SECOND (non-"first()") election, and confirms the
       resulting Ballot is correctly attributed to THAT election --
       not the one cast_ballot_view's form happened to default to --
       because cast_ballot() resolves the election from the submitted
       candidate_id, never from an independent "the open election"
       lookup of its own.
    """
    now = timezone.now()

    election_1 = Election.objects.create(
        title="Election One", start_date=now, end_date=now + timedelta(hours=2)
    )
    candidate_1 = Candidate.objects.create(election=election_1, name="Candidate One")
    election_1.open_voting()  # no error -- nothing blocks this

    election_2 = Election.objects.create(
        title="Election Two", start_date=now, end_date=now + timedelta(hours=2)
    )
    candidate_2 = Candidate.objects.create(election=election_2, name="Candidate Two")
    election_2.open_voting()  # ALSO succeeds -- two OPEN elections now exist simultaneously

    assert Election.objects.filter(status=Election.Status.OPEN).count() == 2

    # --- cast_ballot_view's own election-selection query: no crash ---
    # If this were Election.objects.get(status=OPEN) instead of
    # .filter(...).first(), this line would raise
    # MultipleObjectsReturned right here.
    view_selected_election = Election.objects.filter(status=Election.Status.OPEN).first()
    assert view_selected_election is not None
    assert view_selected_election.pk in (election_1.pk, election_2.pk)
    # Deliberately NOT asserting *which* of the two .first() returns --
    # with no explicit .order_by() in the view, Postgres makes no
    # ordering guarantee for an unordered queryset, and this is not
    # something this investigation needs pinned down. The real,
    # already-documented gap is simply that a voter has no way to
    # CHOOSE which open election cast_ballot_view shows them; which
    # one .first() happens to return is an implementation detail, not
    # part of what Phase 1 needs to prove.

    # BallotForm scopes its candidate queryset to whichever election
    # the view handed it -- so the form the voter would actually see
    # only offers that one election's candidate, never the other's,
    # while both elections are open. Confirmed directly, not assumed,
    # and without caring which election that happens to be:
    expected_candidate = candidate_1 if view_selected_election.pk == election_1.pk else candidate_2
    form = BallotForm(election=view_selected_election)
    assert list(form.fields["candidate"].queryset) == [expected_candidate]

    # --- cast_ballot() itself: explicitly scoped by candidate_id -----
    # Vote for Candidate Two (election_2) directly via the service,
    # bypassing the view's own election-selection step entirely --
    # exactly what would happen if a voter's browser still had a stale
    # link/form referencing election_2's candidate (e.g. two tabs, or
    # the admin having only just opened election_2).
    voter = Voter.objects.create(
        national_id_hash=sha256_hex("61000001"),
        full_name="FR-EL-06 Test Voter",
        phone_number="+254761000001",
    )
    session = issue_session(voter)

    result = cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate_2.candidate_id)

    # The ballot is correctly attributed to election_2 -- the election
    # the CHOSEN CANDIDATE belongs to -- not election_1 (the one the
    # view's .first() would have shown), and not some crash/ambiguous
    # state. cast_ballot() never independently re-derives "the open
    # election"; it only ever resolves Candidate -> its own .election.
    assert result.ballot.election_id == election_2.election_id
    assert result.ballot.candidate_id == candidate_2.candidate_id