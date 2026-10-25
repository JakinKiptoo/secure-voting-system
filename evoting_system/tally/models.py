"""
Tally and Verification Module -- SCHEMA.md lists no entity for this
module (the six-entity ERD predates Sprint 4 being in scope), so this
is a new, additive model, not a change to any existing one.

ElectionResult is the FR-EL-03 "results have been published" gate and
the frozen snapshot a published result is served from. It is
deliberately NOT computed on the fly from live Ballot rows on every
request to the public endpoint (tally/views.py, item 4): publishing is
a one-time, explicit action (item 2) that freezes a tally + proof at
one point in time, and the public endpoint's job is to SERVE that
frozen, published artifact -- not to silently recompute a fresh one
whenever asked, which would make "published" meaningless (an election
could look different on every request).
"""

import uuid

from django.db import models

from elections.models import Election


class ElectionResult(models.Model):
    """
    At most one ElectionResult per Election (OneToOneField) -- a
    second "publish" attempt is rejected by
    tally/services.py::publish_results(), not by re-using this row
    (see that function's docstring for why re-publishing isn't
    supported: a published proof is a frozen point-in-time artifact).

    `published` is the FR-EL-03 gate. In the current flow a row is
    only ever created already published (publish_results() sets
    published=True at creation -- there is no separate "draft result"
    step), so in practice a row's mere existence already implies
    published=True. The field is kept explicit anyway, rather than
    relying on row-existence alone, so every read path
    (tally/services.py::get_verification_payload) states the gate as
    one plain boolean check -- `result.published` -- and so a future
    retract/unpublish action (not built here; out of this sprint's
    scope) would have somewhere to record that without deleting the
    row. Both "no row at all" and "row exists but published=False"
    must render "results not yet published", never an empty/zero
    tally that could be misread as a real 0-0 result (Sprint 4 prompt,
    item 2).
    """

    result_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.OneToOneField(
        Election,
        on_delete=models.PROTECT,
        related_name="result",
        db_column="election_id",
    )
    published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)

    # The frozen tally snapshot. Stored independently of live Ballot
    # rows so the published artifact is exactly reproducible even if
    # the Ballot table were (hypothetically) altered later -- the
    # whole point of tally/services.py's live-vs-published cross-check
    # (FR-P-03's neighbour concern: tamper *detection*, not just
    # tamper *prevention*).
    total_ballots = models.PositiveIntegerField()
    candidate_counts = models.JSONField(
        help_text="candidate_id (str) -> vote count, as of publish time."
    )

    # The pairing-based ZKP (tally/crypto.py::TallyProof), serialized.
    # Field names mirror TallyProof.to_dict()'s keys exactly so
    # (de)serialization is a straight dict round-trip -- see
    # tally/services.py.
    commitment_total_g1 = models.JSONField()
    commitment_total_g2 = models.JSONField()
    candidate_commitments_g1 = models.JSONField()

    # Chain-binding snapshot (item 7 / FR-P-03 tamper-evidence): this
    # election's own slice of the AuditLog hash chain, digested at
    # publish time (auditlog/services.py::election_audit_entries_digest).
    # Re-digested at verification time and compared -- NOT compared
    # against "the chain's current final hash", which would be a false
    # positive on a system running more than one election at once (see
    # that function's docstring).
    audit_entries_digest = models.CharField(max_length=64)
    chain_intact_at_publish = models.BooleanField()
    chain_entries_checked_at_publish = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Election Result"
        verbose_name_plural = "Election Results"

    def __str__(self):
        state = "published" if self.published else "unpublished"
        return f"Result for {self.election} ({state})"
