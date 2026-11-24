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

from dataclasses import dataclass, field

from django.db import connection

from auditlog.models import AuditLog


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


@dataclass
class ChainVerificationResult:
    intact: bool
    entries_checked: int
    # Link check -- populated only when a previous_hash link is broken (the first break):
    break_log_id: int | None = None
    break_timestamp: str | None = None
    expected_previous_hash: str | None = None
    actual_previous_hash: str | None = None
    # Content check: entries whose ballot_hash no longer matches the hash recomputed
    # from their live ballot row (cast_ballot's own formula).
    hash_mismatch_log_ids: list[int] = field(default_factory=list)
    # Completeness checks: ballots with no audit entry, audit entries with no ballot,
    # and elections whose ballot count differs from their audit-entry count.
    ballots_without_entry: int = 0
    entries_without_ballot: int = 0
    count_mismatch_elections: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        if self.intact and self.entries_checked == 0:
            return "No audit log entries exist yet -- nothing to verify."
        if self.intact:
            return (
                f"Chain intact across all {self.entries_checked} "
                f"entr{'y' if self.entries_checked == 1 else 'ies'}, and every entry "
                f"matches its ballot."
            )
        problems = []
        if self.break_log_id is not None:
            problems.append(
                f"Chain broken at log_id={self.break_log_id} "
                f"(timestamp={self.break_timestamp}): expected previous_hash "
                f"{self.expected_previous_hash!r}, found {self.actual_previous_hash!r}."
            )
        if self.hash_mismatch_log_ids:
            problems.append(
                f"{_plural(len(self.hash_mismatch_log_ids), 'audit entry no longer matches', 'audit entries no longer match')} "
                f"the ballot it records (log_id {', '.join(map(str, self.hash_mismatch_log_ids))}): "
                f"the ballot was changed after it was recorded, or the entry's hash was altered."
            )
        if self.ballots_without_entry:
            problems.append(
                f"{_plural(self.ballots_without_entry, 'ballot has', 'ballots have')} no audit entry: "
                f"a ballot was added outside the voting process, or its audit entry was deleted."
            )
        if self.entries_without_ballot:
            problems.append(
                f"{_plural(self.entries_without_ballot, 'audit entry points', 'audit entries point')} "
                f"to a ballot that does not exist."
            )
        if self.count_mismatch_elections:
            problems.append(
                f"The number of ballots and the number of audit entries differ in "
                f"{_plural(len(self.count_mismatch_elections), 'election', 'elections')}."
            )
        return " ".join(problems)


def verify_chain_integrity() -> ChainVerificationResult:
    """
    Walks every AuditLog row in insertion order (log_id ascending) and
    confirms entry.previous_hash == the prior entry's ballot_hash,
    starting from an expected previous_hash of "" for the first row.

    Returns a ChainVerificationResult reporting either "intact" or the
    exact row (log_id + timestamp) where the chain first breaks, and
    the expected vs. actual previous_hash values at that point.

    It also (after the tamper matrix showed the link walk alone misses
    changed or added ballots): recomputes every entry's hash from its
    live Ballot row with cast_ballot's own formula
    (ballots/services.py::_compute_ballot_hash) and records any entry
    that no longer matches; and compares Ballot rows with AuditLog rows
    (ballots without an entry, entries without a ballot, per-election
    counts). The result is intact only if all of these pass. It still
    reads nothing about Voters or Sessions and reports only log_ids and
    counts, never ballot contents.

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
    from ballots.services import _compute_ballot_hash  # local import: ballots imports auditlog

    expected_previous_hash = ""
    checked = 0
    first_break = {}
    mismatches = []

    for entry in AuditLog.objects.select_related("ballot").order_by("log_id").iterator():
        checked += 1
        if not first_break and entry.previous_hash != expected_previous_hash:
            first_break = {
                "break_log_id": entry.log_id,
                "break_timestamp": str(entry.timestamp),
                "expected_previous_hash": expected_previous_hash,
                "actual_previous_hash": entry.previous_hash,
            }
        if _compute_ballot_hash(entry.ballot, entry.previous_hash) != entry.ballot_hash:
            mismatches.append(entry.log_id)
        expected_previous_hash = entry.ballot_hash

    with connection.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM ballots_ballot b "
            "LEFT JOIN auditlog_auditlog a ON a.ballot_id = b.ballot_id WHERE a.log_id IS NULL"
        )
        ballots_without_entry = cur.fetchone()[0]
        cur.execute(
            "SELECT count(*) FROM auditlog_auditlog a "
            "LEFT JOIN ballots_ballot b ON b.ballot_id = a.ballot_id WHERE b.ballot_id IS NULL"
        )
        entries_without_ballot = cur.fetchone()[0]
        cur.execute(
            "SELECT b.election_id FROM ballots_ballot b "
            "LEFT JOIN auditlog_auditlog a ON a.ballot_id = b.ballot_id "
            "GROUP BY b.election_id HAVING count(*) <> count(a.log_id) ORDER BY 1"
        )
        count_mismatch_elections = [str(row[0]) for row in cur.fetchall()]

    intact = not first_break and not mismatches and not ballots_without_entry and not entries_without_ballot \
        and not count_mismatch_elections
    return ChainVerificationResult(
        intact=intact,
        entries_checked=checked,
        hash_mismatch_log_ids=mismatches,
        ballots_without_entry=ballots_without_entry,
        entries_without_ballot=entries_without_ballot,
        count_mismatch_elections=count_mismatch_elections,
        **first_break,
    )


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
