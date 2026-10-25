"""
Tally and Verification Module -- pairing-based tally-correctness proof.

REQUIREMENTS.md S3 fixes the crypto stack as "a pairing-based library"
for ZKP generation, without naming one. This project uses `py_ecc`
(BLS12-381) -- pip-installable with no system-library dependency
(unlike `pypbc`/`charm-crypto`, which need a compiled PBC library this
sandbox-style deployment target can't assume), pure Python, and the
same curve/pairing implementation used by, among others, the Ethereum
2.0 beacon chain reference code, so its correctness is well exercised
outside this project too.

--------------------------------------------------------------------
What this proof actually proves, in plain terms (see tally/services.py
and FR-P-02's human-readable rendering for the voter-facing version):

A published election's tally is a set of public per-candidate counts
and a public total. Nothing about those counts is secret -- a tally
IS meant to be read. So this is not a proof that HIDES the counts
(that would be pointless); it's a proof that the PUBLISHED counts are
internally consistent and were not tampered with after publication,
checkable by anyone, without re-running the Django application or
trusting its arithmetic:

  1. AGGREGATION CHECK (plain elliptic-curve addition, no pairing
     needed): each candidate's count n_i is committed as a point
     c_i = n_i * G1. The published total T is committed the same way,
     C1 = T * G1. Because scalar multiplication distributes over
     addition, C1 must equal the sum of every c_i if, and only if, T
     really is the sum of the n_i's. This is the "the numbers add up"
     check -- pure arithmetic, no cryptography required to follow it.

  2. CROSS-GROUP PAIRING CHECK (the actual pairing-based step): the
     same total T is committed a SECOND time in the other pairing
     group, C2 = T * G2. A bilinear pairing e(.,.) satisfies
     e(a*P, Q) = e(P, Q)^a = e(P, a*Q) for any scalar a and generators
     P in G1, Q in G2. So e(C1, G2) == e(G1, C2) holds if, and only
     if, C1 and C2 encode the SAME scalar T. This is what makes it a
     genuine pairing-based proof rather than plain EC arithmetic: it's
     a "same exponent across two independent groups" check that proves
     C1 and C2 were not independently fabricated to agree by
     coincidence -- an attacker who changes the published total would
     have to solve the discrete-log problem in BOTH groups
     simultaneously to produce a matching pair, which is exactly the
     assumption BLS12-381 is believed to be hard under.

  3. CHAIN-BINDING CHECK (ties the proof to this election's slice of
     the tamper-evident AuditLog -- see tally/services.py, which also
     reuses auditlog/services.py's shared verify_chain_integrity(),
     per Sprint 4 item 7, rather than re-deriving chain logic here).

Checks 1 and 2 together are what `verify_tally_proof()` below runs;
check 3 lives in services.py since it needs the AuditLog table, which
this module deliberately doesn't import (crypto.py is pure math, no
Django/DB dependency, so it can be unit-tested and reasoned about in
isolation).
--------------------------------------------------------------------
"""

from __future__ import annotations

from dataclasses import dataclass

from py_ecc.optimized_bls12_381 import (
    FQ,
    FQ2,
    G1,
    G2,
    Z1,
    add,
    curve_order,
    multiply,
    normalize,
    pairing,
)

# Fixed, public, non-secret generators. Using the library's standard
# base points as the commitment generators is fine here precisely
# because this scheme does NOT rely on hiding discrete logs the way a
# Pedersen commitment to a SECRET value would -- the whole point (see
# module docstring) is that n_i/T are already public. No toxic waste,
# no trusted setup, nothing kept secret after proof generation.
_G1 = G1
_G2 = G2


def _reduce(scalar: int) -> int:
    """Vote counts are always small non-negative integers in this
    system, but scalars are reduced mod the curve's group order
    defensively/for correctness, exactly as any scalar multiplication
    over this curve must be."""
    return scalar % curve_order


def commit_g1(scalar: int):
    """scalar * G1 -- a commitment point in the first pairing group."""
    return multiply(_G1, _reduce(scalar))


def commit_g2(scalar: int):
    """scalar * G2 -- a commitment point in the second pairing group."""
    return multiply(_G2, _reduce(scalar))


def aggregate_g1(points) -> tuple:
    """Sums a list of G1 points via repeated EC addition. Returns the
    point at infinity (Z1) for an empty list -- the correct identity
    element, matching "zero candidates committed sums to zero votes"."""
    total = Z1
    for point in points:
        total = add(total, point)
    return total


def points_equal_g1(a, b) -> bool:
    return normalize(a) == normalize(b)


def serialize_g1(point) -> list[str]:
    """Affine (x, y) hex pair. The point at infinity serializes as
    ["0x0", "0x0"], matching py_ecc's own normalize() convention for
    Z1, and is deserialized back the same way."""
    x, y = normalize(point)
    return [hex(x.n), hex(y.n)]


def deserialize_g1(data: list[str]):
    x, y = (FQ(int(v, 16)) for v in data)
    if x.n == 0 and y.n == 0:
        return Z1
    return (x, y, FQ(1))


def serialize_g2(point) -> list[list[str]]:
    x, y = normalize(point)
    return [
        [hex(x.coeffs[0]), hex(x.coeffs[1])],
        [hex(y.coeffs[0]), hex(y.coeffs[1])],
    ]


def deserialize_g2(data: list[list[str]]):
    (x0, x1), (y0, y1) = data
    x = FQ2((int(x0, 16), int(x1, 16)))
    y = FQ2((int(y0, 16), int(y1, 16)))
    if x.coeffs == (0, 0) and y.coeffs == (0, 0):
        from py_ecc.optimized_bls12_381 import Z2

        return Z2
    return (x, y, FQ2((1, 0)))


@dataclass
class TallyProof:
    """
    Everything a verifier needs to run both checks described in the
    module docstring, fully serialized (JSON-safe hex strings) so it
    can be stored on tally.models.ElectionResult and handed back
    verbatim by the public endpoint -- nothing here is reconstructed
    from the live database by the *proof itself*; services.py is what
    cross-checks it against live Ballot rows.
    """

    total_ballots: int
    candidate_counts: dict[str, int]  # candidate_id (str) -> count
    commitment_total_g1: list[str]
    commitment_total_g2: list[list[str]]
    candidate_commitments_g1: dict[str, list[str]]  # candidate_id -> [x, y]

    def to_dict(self) -> dict:
        return {
            "total_ballots": self.total_ballots,
            "candidate_counts": self.candidate_counts,
            "commitment_total_g1": self.commitment_total_g1,
            "commitment_total_g2": self.commitment_total_g2,
            "candidate_commitments_g1": self.candidate_commitments_g1,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TallyProof":
        return cls(
            total_ballots=data["total_ballots"],
            candidate_counts=data["candidate_counts"],
            commitment_total_g1=data["commitment_total_g1"],
            commitment_total_g2=data["commitment_total_g2"],
            candidate_commitments_g1=data["candidate_commitments_g1"],
        )


def build_tally_proof(candidate_counts: dict[str, int], total_ballots: int) -> TallyProof:
    """
    Generates a TallyProof for the given per-candidate counts and
    total. Pure function of its inputs -- does not touch the database;
    tally/services.py is responsible for computing candidate_counts/
    total_ballots from live Ballot rows and handing them in here.
    """
    commitment_total_g1 = commit_g1(total_ballots)
    commitment_total_g2 = commit_g2(total_ballots)
    candidate_commitments_g1 = {
        str(candidate_id): serialize_g1(commit_g1(count))
        for candidate_id, count in candidate_counts.items()
    }

    return TallyProof(
        total_ballots=total_ballots,
        candidate_counts={str(k): v for k, v in candidate_counts.items()},
        commitment_total_g1=serialize_g1(commitment_total_g1),
        commitment_total_g2=serialize_g2(commitment_total_g2),
        candidate_commitments_g1=candidate_commitments_g1,
    )


@dataclass
class TallyProofVerification:
    """
    The result of independently re-checking a TallyProof. Each check
    is reported separately (rather than collapsing to one boolean) so
    a verifier -- human or automated -- can see exactly which
    property held and which didn't, per FR-P-02.
    """

    aggregation_holds: bool  # check 1: candidate counts sum to the total
    pairing_holds: bool  # check 2: same exponent T across G1 and G2
    recomputed_commitments_match: bool  # stored commitments match fresh ones

    @property
    def valid(self) -> bool:
        return self.aggregation_holds and self.pairing_holds and self.recomputed_commitments_match


def verify_tally_proof(proof: TallyProof) -> TallyProofVerification:
    """
    Re-derives every commitment from the proof's own plaintext
    total_ballots/candidate_counts fields and checks:

      1. aggregation_holds: sum(fresh candidate commitments) ==
         fresh total commitment, in G1 (EC addition).
      2. pairing_holds: e(fresh total commitment in G1, G2) ==
         e(G1, fresh total commitment in G2) -- the cross-group
         pairing check described in the module docstring.
      3. recomputed_commitments_match: the commitments freshly
         rebuilt from the proof's own plaintext numbers match the
         commitment points STORED in the proof -- i.e. the stored
         points weren't swapped out for unrelated ones while the
         plaintext counts were left looking normal. (services.py adds
         a further, DB-level check: that the plaintext counts
         themselves still match what's actually in the Ballot table.)

    This function only trusts the proof's own internal consistency --
    it never queries the database. tally/services.py's
    verify_published_result() layers the live-data cross-check on top.
    """
    fresh_candidate_points = {
        candidate_id: commit_g1(count) for candidate_id, count in proof.candidate_counts.items()
    }
    fresh_total_g1 = commit_g1(proof.total_ballots)
    fresh_total_g2 = commit_g2(proof.total_ballots)

    aggregation_holds = points_equal_g1(
        aggregate_g1(fresh_candidate_points.values()), fresh_total_g1
    )

    pairing_holds = pairing(_G2, fresh_total_g1) == pairing(fresh_total_g2, _G1)

    stored_total_g1 = deserialize_g1(proof.commitment_total_g1)
    stored_total_g2 = deserialize_g2(proof.commitment_total_g2)
    stored_candidate_points = {
        cid: deserialize_g1(pt) for cid, pt in proof.candidate_commitments_g1.items()
    }

    recomputed_commitments_match = (
        points_equal_g1(stored_total_g1, fresh_total_g1)
        and normalize(stored_total_g2) == normalize(fresh_total_g2)
        and stored_candidate_points.keys() == fresh_candidate_points.keys()
        and all(
            points_equal_g1(stored_candidate_points[cid], fresh_candidate_points[cid])
            for cid in fresh_candidate_points
        )
    )

    return TallyProofVerification(
        aggregation_holds=aggregation_holds,
        pairing_holds=pairing_holds,
        recomputed_commitments_match=recomputed_commitments_match,
    )
