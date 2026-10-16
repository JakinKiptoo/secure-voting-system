"""
Ballot Casting Module -- the atomic ballot-casting transaction.

Implements the Ballot Casting sequence diagram (DIAGRAMS.md S4.5.4)
in EXACT step order -- record ballot -> hash+append to AuditLog ->
destroy token -> set has_voted -> confirm -- which differs from the
FR-V-05/06/07 numbering order; the diagram wins (DIAGRAMS.md's own
stated rule, not just this module's interpretation). Covers FR-V-04
to FR-V-08, the ballot-side of FR-A-03, and FR-DB-01's write path
(the actual insert-only enforcement is a DB-role grant, not code --
see scripts/setup_db_roles.sql).

FR-EL-05 update: step 5 ("set has_voted") is now scoped to the
specific Election being voted in via VoterElectionParticipation,
not (only) the old global Voter.has_voted boolean -- see that model's
docstring (voters/models.py) and the FR-EL-05 handover for why a
single global boolean can't survive more than one Election existing
over the system's lifetime. Voter.has_voted is still set here too,
but only as a repurposed, non-gating "voted in at least one election,
ever" convenience flag -- nothing in this function reads it to decide
whether a ballot may be cast; that decision is now entirely
VoterElectionParticipation's.
"""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from auditlog.models import AuditLog
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voters.crypto_utils import sha256_hex
from voters.models import VoterElectionParticipation

from .models import Ballot


class BallotCastError(Exception):
    """Raised for any reason a ballot cast is rejected. Caller (the
    view) renders `str(exc)` as the user-facing rejection message."""


@dataclass
class BallotCastResult:
    ballot: Ballot
    audit_entry: AuditLog


def _compute_ballot_hash(ballot: Ballot, previous_hash: str) -> str:
    """
    SHA-256 over a canonical string of the ballot's identifying fields
    plus the previous entry's hash, so the AuditLog chain itself is
    verifiable (SCHEMA.md AuditLog.previous_hash) -- tampering with
    any prior entry changes every hash after it.

    Deliberately excludes any voter-identifying data (there is none
    available here anyway -- Ballot carries no such reference) so the
    hash can never be used to reconstruct who cast the ballot (FR-P-03
    concern, even though this hash isn't the public endpoint itself).
    """
    canonical = "|".join(
        [
            str(ballot.ballot_id),
            str(ballot.election_id),
            str(ballot.candidate_id),
            ballot.created_at.isoformat(),
            previous_hash,
        ]
    )
    return sha256_hex(canonical)


@transaction.atomic
def cast_ballot(uuid_token: str, candidate_id) -> BallotCastResult:
    """
    Cast one ballot for the Session identified by `uuid_token`,
    selecting `candidate_id`. Raises BallotCastError with a
    user-facing message for every rejection path; raises nothing and
    returns a BallotCastResult on success, after which every write
    below has committed.

    Step order below matches DIAGRAMS.md S4.5.4 exactly:
      1. Verify token against Session record
      2. Record the Ballot
      3. Compute + append SHA-256 hash to AuditLog
      4. Destroy the Session token
      5. Set participation (VoterElectionParticipation, FR-EL-05) +
         the legacy Voter.has_voted convenience flag
      6. (confirmation is the caller's job, once this returns)
    Any exception anywhere below rolls the whole transaction back --
    no partial ballot state, per DIAGRAMS.md's explicit "roll back in
    full" note.

    The candidate/election lookup and the per-election double-vote
    check (below) now happen BEFORE "record the Ballot", ahead of
    where they sat relative to step 2 before FR-EL-05 -- they always
    had to happen before Ballot creation (the Ballot needs a resolved
    Candidate), this just makes the double-vote check itself scoped to
    that same, now-known Election, rather than checking a global flag
    before the election was even looked up.
    """
    # --- Step 1: verify token against Session record ---------------
    # A Session is only a valid token if it's active AND not expired --
    # both conditions are folded into one query (rather than fetching
    # first and checking expiry after) so an expired-but-still-active
    # row is rejected before any transaction work begins, and so it
    # gets the exact same rejection a voter sees for a token that
    # doesn't exist/was already used at all -- deliberately not a
    # distinguishable "expired" message, so the rejection can't be
    # used to tell an attacker which case applies.
    try:
        session = Session.objects.select_for_update().get(
            uuid_token=uuid_token,
            is_active=True,
            expiry_time__gt=timezone.now(),
        )
    except Session.DoesNotExist as exc:
        raise BallotCastError(
            "Your session is invalid or has expired. Please log in again."
        ) from exc

    voter = session.voter  # transient use only -- never persisted onto Ballot

    try:
        candidate = Candidate.objects.select_related("election").get(pk=candidate_id)
    except Candidate.DoesNotExist as exc:
        raise BallotCastError("Selected candidate does not exist.") from exc

    election = candidate.election

    # FR-A-03 (ballot side): reject ballots submitted outside an open
    # voting period.
    if election.status != Election.Status.OPEN:
        raise BallotCastError("This election is not currently open for voting.")

    # FR-EL-05: defensive, per-ELECTION re-check, NOT pictured in the
    # sequence diagram (which only checks has_voted during
    # authentication, FR-V-02, now itself rescoped the same way in
    # voters/views.py). Added in Sprint 3 (then global, now scoped
    # here) because Sprint 2 does not invalidate a voter's other
    # active Sessions on a new login -- without this, a voter who
    # logged in twice could cast a second ballot for the SAME election
    # with their second token after their first vote in it already
    # recorded. select_for_update() locks any existing row for the
    # duration of this transaction so two concurrent casts for the
    # same (voter, election) can't both pass this check before either
    # commits -- the same race-closing pattern as the Session and
    # AuditLog locks elsewhere in this function. Deliberately does NOT
    # check any OTHER election's participation: a voter who already
    # voted in a different election must still be able to vote here.
    participation, _ = VoterElectionParticipation.objects.select_for_update().get_or_create(
        voter=voter, election=election
    )
    if participation.has_voted:
        raise BallotCastError("This voter has already cast a ballot in this election.")

    # --- Step 2: record the Ballot ----------------------------------
    ballot = Ballot.objects.create(election=election, candidate=candidate)

    # --- Step 3: compute + append SHA-256 hash to AuditLog ----------
    previous_entry = AuditLog.objects.select_for_update().order_by("-log_id").first()
    previous_hash = previous_entry.ballot_hash if previous_entry else ""
    ballot_hash = _compute_ballot_hash(ballot, previous_hash)
    audit_entry = AuditLog.objects.create(
        ballot=ballot,
        action_type="ballot_cast",
        ballot_hash=ballot_hash,
        previous_hash=previous_hash,
    )

    # --- Step 4: destroy the Session token ---------------------------
    # Deactivate rather than delete the row: Session.is_active exists
    # on the model precisely to represent "this token no longer
    # works" (its own docstring says the record is "invalidated",
    # not removed). Deactivating (and the explicit update_fields
    # below, so this is a real UPDATE, not just an in-memory
    # attribute change that looks right in the same request but never
    # reaches the database) also keeps the row around as an audit
    # trail of which session cast which ballot, without ever
    # persisting a reverse Ballot->Session/Voter reference anywhere.
    session.is_active = False
    session.save(update_fields=["is_active"])

    # --- Step 5: set participation (FR-EL-05) + legacy has_voted ----
    # `participation` is the SAME row locked and fetched above (via
    # select_for_update + get_or_create), so this is an UPDATE of that
    # row, not a second/competing fetch.
    participation.has_voted = True
    participation.voted_at = timezone.now()
    participation.save(update_fields=["has_voted", "voted_at"])

    # Legacy global convenience flag only (see Voter.has_voted's
    # help_text and the module docstring above) -- never read by this
    # function or by voters/views.py to gate anything; kept in sync
    # purely so "has this voter voted in at least one election, ever"
    # stays accurate for any display/reporting use.
    if not voter.has_voted:
        voter.has_voted = True
        voter.save(update_fields=["has_voted"])

    # --- Step 6: confirmation is the view's job, using the return ----
    return BallotCastResult(ballot=ballot, audit_entry=audit_entry)
