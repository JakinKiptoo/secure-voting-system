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
