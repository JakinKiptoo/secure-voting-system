"""
FR-AUD-02: hash-chain integrity verification.

A pure walk over auditlog.AuditLog's own columns -- log_id, timestamp,
ballot_hash, previous_hash. This deliberately never looks at Ballot,
Session, or Voter: the chain property it checks (each row's
previous_hash equals the prior row's ballot_hash, with the first row
chaining from "") is entirely self-contained within AuditLog, exactly
as ballots/services.py's cast_ballot() constructs it
(previous_hash = previous_entry.ballot_hash if previous_entry else "").

Ordering: by log_id ascending -- the auto-incrementing PK, i.e. true
insertion order -- not by timestamp. timestamp is an auto_now_add
DateTimeField with no uniqueness guarantee; log_id is the authoritative
ordering key and is what cast_ballot() itself uses
(select_for_update().order_by("-log_id").first()) to find "the
previous entry". timestamp is still included in the result for human
readability when reporting where a chain breaks.

Sprint 4 note (moved here from auditors/services.py): this module used
to live inside the auditors/ app (Thread A, Part 2), since Auditors'
FR-AUD-02 dashboard check was its only caller. Sprint 4's public tally
endpoint (tally/, item 7 of its prompt) needs the exact same "is the
chain intact" walk -- not a second, independently-written one that
could silently drift out of sync with this one. auditlog/ (the Audit
Log Module itself, one of the six fixed modules, REQUIREMENTS.md S4)
is the correct shared home for it: both auditors/ (an extension-track
role dashboard) and tally/ (a core module) depend on auditlog/, so
putting the shared logic here -- rather than leaving it in auditors/,
which tally/ has no business depending on -- keeps the dependency
direction pointing the right way. auditors/services.py now just
re-exports these two names so auditors/views.py and auditors/tests.py
didn't need to change at all; see that file's docstring.
"""

from dataclasses import dataclass

from auditlog.models import AuditLog


@dataclass
class ChainVerificationResult:
    intact: bool
    entries_checked: int
    # Populated only when intact is False:
    break_log_id: int | None = None
    break_timestamp: str | None = None
    expected_previous_hash: str | None = None
    actual_previous_hash: str | None = None

    @property
    def summary(self) -> str:
        if self.entries_checked == 0:
            return "No audit log entries exist yet -- nothing to verify."
        if self.intact:
            return (
                f"Chain intact across all {self.entries_checked} "
                f"entr{'y' if self.entries_checked == 1 else 'ies'}."
            )
        return (
            f"Chain broken at log_id={self.break_log_id} "
            f"(timestamp={self.break_timestamp}): expected previous_hash "
            f"{self.expected_previous_hash!r}, found {self.actual_previous_hash!r}."
        )


def verify_chain_integrity() -> ChainVerificationResult:
    """
    Walks every AuditLog row in insertion order (log_id ascending) and
    confirms entry.previous_hash == the prior entry's ballot_hash,
    starting from an expected previous_hash of "" for the first row.

    Returns a ChainVerificationResult reporting either "intact" or the
    exact row (log_id + timestamp) where the chain first breaks, and
    the expected vs. actual previous_hash values at that point -- never
    anything about which Ballot/Voter/Session that row's hash belongs
    to, since this check doesn't query those tables at all.

    Deliberately GLOBAL, not scoped to one election: the chain this
    project builds is a single system-wide insertion-ordered sequence
    across every election's ballots (cast_ballot() always chains from
    "whatever the globally-most-recent AuditLog row is", regardless of
    which election it belongs to -- see ballots/services.py). There is
    no such thing as "election X's own independent chain" to walk, so
    tally/services.py (Sprint 4) calls this SAME function for its
    chain-intactness check rather than attempting a per-election walk
    of its own, and separately filters AuditLog by
    `ballot__election=X` (see
    election_audit_entries_digest() below) for "which hashes belong to
    this election" -- a filter, not a second chain-walk implementation.
    """
    expected_previous_hash = ""
    checked = 0

    for entry in AuditLog.objects.order_by("log_id").iterator():
        checked += 1
        if entry.previous_hash != expected_previous_hash:
            return ChainVerificationResult(
                intact=False,
                entries_checked=checked,
                break_log_id=entry.log_id,
                break_timestamp=str(entry.timestamp),
                expected_previous_hash=expected_previous_hash,
                actual_previous_hash=entry.previous_hash,
            )
        expected_previous_hash = entry.ballot_hash

    return ChainVerificationResult(intact=True, entries_checked=checked)


def election_audit_entries(election):
    """
    The subset of AuditLog rows whose Ballot belongs to the given
    Election, in insertion order (log_id ascending). A plain filtered
    query -- NOT an independent chain-walk -- used by tally/services.py
    to know "which of the globally-chained hashes are this election's
    own" (for display, per FR-P-01's "serving that election's ...
    AuditLog hashes") and to detect whether this election's own slice
    of the log has changed since results were published (see
    election_audit_entries_digest() below). Whether the chain AS A
    WHOLE is intact is a separate, global question -- answered by
    verify_chain_integrity() above, not by anything scoped here.
    """
    return AuditLog.objects.filter(ballot__election=election).order_by("log_id")


def election_audit_entries_digest(election) -> str:
    """
    A single SHA-256 hex digest summarising exactly this election's
    AuditLog entries (log_id + ballot_hash pairs, in insertion order).
    Recomputing this later and comparing against a value stored at
    publish time (tally/models.py::ElectionResult) is how Sprint 4's
    tally proof detects whether THIS election's own rows have been
    altered since publication -- independent of the global chain
    continuing to grow from other elections' activity in the meantime,
    which would otherwise make a naive "does the chain's current last
    hash still match" check fail for entirely innocent reasons on a
    system that runs more than one election at a time (FR-EL-06).
    """
    import hashlib

    entries = election_audit_entries(election)
    payload = "|".join(f"{entry.log_id}:{entry.ballot_hash}" for entry in entries)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
