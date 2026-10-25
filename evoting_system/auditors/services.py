"""
FR-AUD-02: hash-chain integrity verification.

Sprint 4 note: the actual chain-walk logic that used to live in this
file (Thread A, Part 2) has moved to auditlog/services.py, since
Sprint 4's public tally endpoint (tally/) needs the exact same "is the
chain intact" walk and must not get a second, independently-written
copy that could silently drift out of sync with this one (Sprint 4
prompt, item 7). auditlog/ -- the Audit Log Module itself -- is the
correct shared home: both auditors/ (an extension-track role
dashboard) and tally/ (a core module) depend on it, whereas tally/
depending on auditors/ would point the module dependency graph the
wrong way round.

ChainVerificationResult and verify_chain_integrity are re-exported
here, under these same names, so auditors/views.py and
auditors/tests.py (Part 2, unmodified) don't need to change at all --
same pattern officials/permissions.py already uses for its own thin
wrappers around common/roles.py. See auditlog/services.py for the full
implementation and reasoning.
"""

from auditlog.services import ChainVerificationResult, verify_chain_integrity

__all__ = ["ChainVerificationResult", "verify_chain_integrity"]
