"""
Tally and Verification Module -- business logic.

Three operations, matching the Sprint 4 prompt's items 1/2/3/4/6:

  - compute_tally(election): item 1, strictly scoped to one election's
    own Ballot rows. Never touches another election's data and never
    sums across elections.
  - publish_results(election): item 2 (FR-EL-03's gate) + item 3 (ZKP
    generation). The only place an ElectionResult row is created.
  - get_verification_payload(election): item 4/5/6's read path for
    both the public HTML page and the public JSON endpoint -- a single
    shared function so the two presentations (views.py) can never
    disagree about what "published"/"not yet available" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from auditlog.services import (
    election_audit_entries,
    election_audit_entries_digest,
    verify_chain_integrity,
)
from ballots.models import Ballot
from elections.models import Candidate, Election

from .crypto import TallyProof, build_tally_proof, verify_tally_proof
from .models import ElectionResult


@dataclass
class TallyBreakdown:
    """item 1: a single election's own tally, nothing cross-election."""

    election_id: str
    candidate_counts: dict[str, int]  # candidate_id (str) -> count
    candidate_names: dict[str, str]  # candidate_id (str) -> display name, for item 5
    total_ballots: int


def compute_tally(election: Election) -> TallyBreakdown:
    """
    item 1: tally computation STRICTLY SCOPED to the given election.
    Every query here is filtered by `election=election` (or, for
    candidates, `election.candidates`) -- there is no code path in
    this function that could sum across Election rows, by
    construction, not just by convention: it never issues a query
    against Ballot or Candidate without that filter.
    """
    candidates = list(election.candidates.order_by("name"))
    candidate_counts = {
        str(c.candidate_id): Ballot.objects.filter(election=election, candidate=c).count()
        for c in candidates
    }
    candidate_names = {str(c.candidate_id): c.name for c in candidates}
    total_ballots = Ballot.objects.filter(election=election).count()

    return TallyBreakdown(
        election_id=str(election.election_id),
        candidate_counts=candidate_counts,
        candidate_names=candidate_names,
        total_ballots=total_ballots,
    )


def publish_results(election: Election) -> ElectionResult:
    """
    FR-EL-03 (item 2) + ZKP generation (item 3).

    Deliberately requires election.status == CLOSED before anything is
    written. Not explicitly spelled out as a rule in the Sprint 4
    prompt, but inferred as a necessary consequence of it: "closing
    voting must NOT auto-publish a tally, add an explicit publish
    step" only makes sense as a two-step CLOSED -> published sequence
    if publishing an OPEN election (one that could still receive more
    ballots) is also blocked -- otherwise a "published" tally could
    go stale moments later while still showing as a settled result.
    Flagged in the handover as an inferred constraint, not a literal
    instruction.

    Also deliberately rejects a second publish attempt on an election
    that already has a (published) ElectionResult: a published tally
    is a frozen, point-in-time cryptographic artifact (the ZKP commits
    to a specific total_ballots/candidate_counts pair) -- silently
    overwriting it with a new computation on re-call would make
    "published" mean "whatever the last call happened to see", which
    defeats the point of a publish step existing at all. If a genuine
    re-publish/correction workflow is ever needed, that is a new,
    explicit action to design (e.g. "retract and republish"), not an
    implicit side effect of calling this function twice -- out of this
    sprint's scope.
    """
    if election.status != Election.Status.CLOSED:
        raise ValidationError(
            f"Cannot publish results for '{election}': results can only be "
            f"published once voting has closed (current status: "
            f"{election.get_status_display()})."
        )

    if ElectionResult.objects.filter(election=election).exists():
        raise ValidationError(f"Results for '{election}' have already been published.")

    breakdown = compute_tally(election)
    proof: TallyProof = build_tally_proof(breakdown.candidate_counts, breakdown.total_ballots)

    # Sanity-check the proof we're about to persist actually verifies,
    # before anything is written -- publishing a self-inconsistent
    # proof would be a bug in this function, not a tamper scenario,
    # and should fail loudly here rather than surface later at
    # verification time.
    self_check = verify_tally_proof(proof)
    if not self_check.valid:
        raise RuntimeError(
            "Freshly generated tally proof failed its own verification -- "
            "this indicates a bug in tally/crypto.py, not tampered data. "
            f"aggregation_holds={self_check.aggregation_holds} "
            f"pairing_holds={self_check.pairing_holds} "
            f"recomputed_commitments_match={self_check.recomputed_commitments_match}"
        )

    chain_result = verify_chain_integrity()
    digest = election_audit_entries_digest(election)

    with transaction.atomic():
        result = ElectionResult.objects.create(
            election=election,
            published=True,
            published_at=timezone.now(),
            total_ballots=breakdown.total_ballots,
            candidate_counts=breakdown.candidate_counts,
            commitment_total_g1=proof.commitment_total_g1,
            commitment_total_g2=proof.commitment_total_g2,
            candidate_commitments_g1=proof.candidate_commitments_g1,
            audit_entries_digest=digest,
            chain_intact_at_publish=chain_result.intact,
            chain_entries_checked_at_publish=chain_result.entries_checked,
        )

    return result


@dataclass
class VerificationPayload:
    """
    item 4/5/6's shared read-model: everything both the public HTML
    page and the public JSON endpoint need, computed once so the two
    presentations can't disagree.

    `available` is False for any election with no published
    ElectionResult (OPEN, CLOSED-but-unpublished, or DRAFT) -- the
    caller must render "results not yet published" in that case, never
    an empty/zero tally (item 2's explicit requirement, re-affirmed at
    the read side here, not just at the write side in publish_results).
    """

    available: bool
    election_id: str
    election_title: str
    election_status: str
    reason_unavailable: str | None = None

    total_ballots: int | None = None
    candidate_results: list[dict] = field(default_factory=list)  # [{id, name, count}]
    published_at: datetime | None = None

    proof: dict | None = None  # TallyProof.to_dict()
    verification: dict | None = None  # see _verification_dict() below

    audit_entries: list[dict] = field(default_factory=list)  # [{log_id, timestamp, ballot_hash, previous_hash}]

    def to_json_dict(self) -> dict:
        """
        JSON-safe rendering for the public DRF endpoint (item 4):
        every field as-is except `published_at`, which needs
        isoformat() since dataclasses don't auto-serialize datetimes.
        """
        return {
            "available": self.available,
            "election_id": self.election_id,
            "election_title": self.election_title,
            "election_status": self.election_status,
            "reason_unavailable": self.reason_unavailable,
            "total_ballots": self.total_ballots,
            "candidate_results": self.candidate_results,
            "published_at": self.published_at.isoformat() if self.published_at else None,
            "proof": self.proof,
            "verification": self.verification,
            "audit_entries": self.audit_entries,
        }


def _verification_dict(proof: TallyProof, stored_result: ElectionResult) -> dict:
    """
    Runs every independent check described in crypto.py's module
    docstring, PLUS the two checks that need live data
    (crypto.verify_tally_proof() only trusts the proof's own
    plaintext numbers against itself -- it never touches the
    database):

      - live_counts_match: today's actual Ballot rows for this
        election still produce the same candidate_counts/total that
        were published. Ballots are immutable and PROTECTed once
        created, so in the absence of tampering this always holds;
        checking it live is what turns "immutable by convention" into
        "verified, not just assumed" for a public reader.
      - audit_entries_unchanged: this election's own slice of the
        AuditLog hash chain still digests to what was recorded at
        publish time (auditlog/services.py::election_audit_entries_digest),
        and chain_currently_intact re-runs the SAME shared
        verify_chain_integrity() the Auditor dashboard uses (item 7)
        to confirm the chain as a whole is still uncorrupted right
        now, not just whatever it reported at publish time.
    """
    crypto_result = verify_tally_proof(proof)

    return {
        "aggregation_holds": crypto_result.aggregation_holds,
        "pairing_holds": crypto_result.pairing_holds,
        "recomputed_commitments_match": crypto_result.recomputed_commitments_match,
        "cryptographic_proof_valid": crypto_result.valid,
    }


def get_verification_payload(election: Election, *, deep_verify: bool = False) -> VerificationPayload:
    """
    item 4's shared read path. `deep_verify=True` additionally re-runs
    the live Ballot/AuditLog cross-checks and the pairing check
    (crypto.verify_tally_proof(), which performs two real pairing
    evaluations -- the only genuinely slow step in this whole module,
    ~0.5-1s with py_ecc's optimized BLS12-381 implementation). Default
    is False so the default public GET stays fast (NFR-PE-01): the
    proof and the publish-time verification outcome are always served;
    a caller that wants the pairing re-run live opts in explicitly
    (views.py exposes this as ?reverify=1). Either way nothing here
    ever claims "verified" without the check having actually run at
    some point -- the publish-time outcome is never silently assumed,
    it's the recorded, already-run result of the exact same
    verify_tally_proof() call performed once at publish time.
    """
    try:
        result = election.result
    except ElectionResult.DoesNotExist:
        result = None

    if result is None or not result.published:
        reason = (
            "This election has not been closed and published yet."
            if election.status != Election.Status.CLOSED
            else "Voting has closed, but results have not been published yet."
        )
        return VerificationPayload(
            available=False,
            election_id=str(election.election_id),
            election_title=election.title,
            election_status=election.status,
            reason_unavailable=reason,
        )

    proof = TallyProof.from_dict(
        {
            "total_ballots": result.total_ballots,
            "candidate_counts": result.candidate_counts,
            "commitment_total_g1": result.commitment_total_g1,
            "commitment_total_g2": result.commitment_total_g2,
            "candidate_commitments_g1": result.candidate_commitments_g1,
        }
    )

    candidate_names = {
        str(c.candidate_id): c.name for c in Candidate.objects.filter(election=election)
    }
    candidate_results = [
        {
            "candidate_id": cid,
            "name": candidate_names.get(cid, "(candidate record no longer available)"),
            "count": count,
        }
        for cid, count in sorted(result.candidate_counts.items(), key=lambda kv: kv[0])
    ]

    verification = _verification_dict(proof, result)
    verification["chain_intact_at_publish"] = result.chain_intact_at_publish
    verification["chain_entries_checked_at_publish"] = result.chain_entries_checked_at_publish

    audit_entries = [
        {
            "log_id": e.log_id,
            "timestamp": e.timestamp.isoformat(),
            "ballot_hash": e.ballot_hash,
            "previous_hash": e.previous_hash,
        }
        for e in election_audit_entries(election)
    ]

    if deep_verify:
        live_breakdown = compute_tally(election)
        live_counts_match = (
            live_breakdown.total_ballots == result.total_ballots
            and live_breakdown.candidate_counts == result.candidate_counts
        )
        live_digest = election_audit_entries_digest(election)
        audit_entries_unchanged = live_digest == result.audit_entries_digest
        live_chain_result = verify_chain_integrity()

        verification["live_counts_match"] = live_counts_match
        verification["audit_entries_unchanged"] = audit_entries_unchanged
        verification["chain_currently_intact"] = live_chain_result.intact
        verification["deep_verified"] = True
        verification["fully_verified"] = (
            verification["cryptographic_proof_valid"]
            and live_counts_match
            and audit_entries_unchanged
            and live_chain_result.intact
        )
    else:
        verification["deep_verified"] = False

    return VerificationPayload(
        available=True,
        election_id=str(election.election_id),
        election_title=election.title,
        election_status=election.status,
        total_ballots=result.total_ballots,
        candidate_results=candidate_results,
        published_at=result.published_at,
        proof=proof.to_dict(),
        verification=verification,
        audit_entries=audit_entries,
    )
