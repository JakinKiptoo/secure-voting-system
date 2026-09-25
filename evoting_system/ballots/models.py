import uuid

from django.db import models

from elections.models import Candidate, Election


class Ballot(models.Model):
    """
    Ballot Casting Module -- SCHEMA.md "Ballot".

    Non-negotiable design invariant (CLAUDE.md #1, REQUIREMENTS.md S5,
    SCHEMA.md "Non-negotiable structural rule"): this model has NO
    foreign key to Voter or Session, ever -- not once submission
    completes, not transiently, not for a "convenience" admin query.
    The UUID session token is the only voter<->ballot link at runtime,
    passed through the view/service layer and never persisted here.
    If a future feature seems to need Ballot.voter or Ballot.session,
    the feature is wrong, not this model -- flag it, don't add the FK.

    The atomic ballot-casting transaction (record ballot -> hash into
    AuditLog -> destroy token -> set has_voted -> confirm) and its
    view are Sprint 3 scope (FR-V-04 to FR-V-07). This model only
    provides the storage shape for that later work.
    """

    ballot_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.ForeignKey(
        Election,
        on_delete=models.PROTECT,
        related_name="ballots",
        db_column="election_id",
    )
    candidate = models.ForeignKey(
        Candidate,
        on_delete=models.PROTECT,
        related_name="ballots",
        db_column="candidate_id",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Ballot"
        verbose_name_plural = "Ballots"

    def __str__(self):
        return f"Ballot {self.ballot_id}"
