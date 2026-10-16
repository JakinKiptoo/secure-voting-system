"""
FR-EL-05: per-election-scoped eligibility check for authentication
(FR-V-02), extracted into its own small module so credentials_view()
stays thin and this logic is unit-testable without going through the
whole view.

FR-V-02 originally read "check has_voted at authentication; reject if
already set" against a single global boolean. That's now wrong given
more than one Election can exist over the system's lifetime: a voter
who already voted in Election A must still be able to authenticate to
vote in Election B. See voters/models.py's VoterElectionParticipation
docstring for the full per-election tracking design.

Authentication happens BEFORE a voter picks a candidate (and therefore
before the specific Election they're about to vote in is known), so
this can't check participation against "the election they're casting
a ballot for" the way ballots/services.py's cast_ballot() does -- it
can only check against whichever Election(s) are currently open for
voting right now.
"""

from elections.models import Election

from .models import VoterElectionParticipation


def voter_has_an_open_election_left_to_vote_in(voter) -> bool:
    """
    True if there is at least one currently-OPEN Election this voter
    has NOT already voted in -- i.e. true when authentication should
    be ALLOWED to proceed; false when it should be rejected under
    FR-V-02.

    - No Election is currently OPEN at all: returns True (nothing to
      reject against at login time -- this matches the pre-FR-EL-05
      behaviour, where FR-A-03's "no open election" rejection happens
      later, at ballot-casting time, not at login).
    - Exactly one Election is OPEN (the expected steady-state case:
      this project runs elections sequentially, not concurrently):
      True unless the voter already has a has_voted=True
      participation row for it.
    - More than one Election is OPEN at once (not how this system is
      meant to be operated, per REQUIREMENTS.md/CLAUDE.md, but nothing
      in the schema technically prevents it): True as long as at
      least one of them is still unvoted-in by this voter -- a voter
      who voted in some but not all currently-open elections must
      still be allowed to authenticate, since they may be here for
      one of the remaining ones. Only rejected once they've already
      voted in EVERY currently-open election.
    """
    open_election_ids = set(
        Election.objects.filter(status=Election.Status.OPEN).values_list(
            "election_id", flat=True
        )
    )
    if not open_election_ids:
        return True

    voted_election_ids = set(
        VoterElectionParticipation.objects.filter(
            voter=voter, election_id__in=open_election_ids, has_voted=True
        ).values_list("election_id", flat=True)
    )

    return not open_election_ids.issubset(voted_election_ids)
