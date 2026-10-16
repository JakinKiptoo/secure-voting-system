import uuid

from django.db import models

from elections.models import Election


class Voter(models.Model):
    """
    Voter Authentication Module -- SCHEMA.md "Voter".

    Non-negotiable design invariant (CLAUDE.md #1, REQUIREMENTS.md S5):
    this model holds NO attribute or relationship referencing any
    Ballot instance, directly or indirectly. Anonymisation is enforced
    structurally by the absence of that field, not by convention. Do
    not add a `ballot` / `ballots` field here under any circumstances.
    """

    voter_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    national_id_hash = models.CharField(
        max_length=255,
        unique=True,
        help_text=(
            "Hashed National ID -- the raw National ID is never stored. "
            "unique=True enforces FR-V-00's uniqueness requirement at "
            "the database level (Sprint 3 correction): the application-"
            "layer check in VoterRegistrationForm.clean_national_id "
            "alone can't stop two concurrent registration requests for "
            "the same National ID both passing validation before either "
            "commits -- the DB constraint is what actually closes that "
            "race."
        ),
    )
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    otp_hash = models.CharField(
        max_length=255,
        blank=True,
        help_text="Hashed OTP secret. Populated by the MFA pipeline (Sprint 2, FR-V-03).",
    )
    registration_date = models.DateTimeField(
        auto_now_add=True,
        help_text="Set under FR-V-00 at registration time.",
    )
    has_voted = models.BooleanField(
        default=False,
        help_text=(
            "FR-EL-05 repurposing: this is NO LONGER the source of "
            "truth for ballot-casting or authentication eligibility -- "
            "VoterElectionParticipation.has_voted (scoped per Election) "
            "is. This field is kept only as a global convenience/"
            "display flag meaning \"has this voter voted in at least "
            "one election, ever\" -- set alongside a participation row "
            "being marked voted, but never read by cast_ballot() or "
            "credentials_view() to gate anything. See "
            "VoterElectionParticipation below and the FR-EL-05 "
            "handover for why: a single global boolean can't represent "
            "\"voted in election A, still eligible for election B\" "
            "once more than one Election exists over the system's "
            "lifetime."
        ),
    )

    class Meta:
        verbose_name = "Voter"
        verbose_name_plural = "Voters"

    def __str__(self):
        return f"Voter {self.voter_id}"


class VoterElectionParticipation(models.Model):
    """
    FR-EL-05: per-election participation tracking -- the poll-book,
    not the ballot box.

    Tracks ONLY the fact that a specific Voter participated in a
    specific Election (has_voted + voted_at). It deliberately carries
    no reference, direct or indirect, to Candidate or Ballot, and
    nothing on Ballot or Candidate references this model either --
    this draws exactly the same line SCHEMA.md's "Non-negotiable
    structural rule" draws for Ballot itself: knowing THAT a voter
    voted in an election is not the same as knowing WHAT they voted
    for, and this model only ever answers the first question. See
    voters/tests.py's anonymity-invariant test for how this is
    verified, not just asserted (the same rigor as Thread A's leak
    tests).

    This is what makes it safe to run more than one Election over the
    system's lifetime: Voter.has_voted was a single global boolean,
    so a voter who voted in Election A was permanently (and wrongly)
    locked out of every later Election. A row here is scoped to one
    (voter, election) pair instead.

    unique_together enforces at the DB level that a given voter can
    have at most one participation row per election -- the row is
    created (or fetched) once a voter is known to be voting in that
    election, and its has_voted/voted_at fields are only ever set
    True/populated from inside cast_ballot()'s atomic transaction,
    mirroring exactly how Voter.has_voted used to be set (FR-V-06),
    just now scoped to the right row.

    on_delete=PROTECT on both FKs, matching Ballot's own PROTECT to
    Election/Candidate (ballots/models.py) -- an Election or Voter
    being deleted must never silently discard participation history.
    """

    voter = models.ForeignKey(
        "voters.Voter",
        on_delete=models.PROTECT,
        related_name="election_participations",
        db_column="voter_id",
    )
    election = models.ForeignKey(
        Election,
        on_delete=models.PROTECT,
        related_name="voter_participations",
        db_column="election_id",
    )
    has_voted = models.BooleanField(default=False)
    voted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Voter Election Participation"
        verbose_name_plural = "Voter Election Participations"
        unique_together = ("voter", "election")

    def __str__(self):
        return f"{self.voter_id} in {self.election_id} (voted={self.has_voted})"
