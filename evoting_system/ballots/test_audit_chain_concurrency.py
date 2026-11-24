"""
FR-V-07 / FR-AUD-02: concurrent casts must append to the audit hash chain one
after another, never both to the same tail (a fork). Found on evoting_perf,
where log_ids 36 and 37 both had previous_hash = ballot_hash of 35 after a
"5 voters at a time" run.

Threads use their own database connections with real commits. The audit-hash
step (_compute_ballot_hash, which runs right after the tail is read and before
the new AuditLog row is inserted) is slowed by 50 ms to widen the window.
"""

import threading
import time
from collections import Counter
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from auditlog.models import AuditLog
from auditlog.services import verify_chain_integrity
from ballots import services as ballot_services
from ballots.services import cast_ballot
from elections.models import Candidate, Election
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

N = 8


@pytest.mark.django_db(transaction=True)
def test_fr_v07_fr_aud02_concurrent_casts_keep_the_audit_chain_linear(monkeypatch):
    now = timezone.now()
    election = Election.objects.create(title="Chain Election", start_date=now, end_date=now + timedelta(hours=2))
    cands = [Candidate.objects.create(election=election, name=f"Chain Candidate {i}") for i in range(2)]
    election.open_voting()
    tokens = []
    for i in range(N):
        v = Voter.objects.create(national_id_hash=sha256_hex(f"7800{i:04d}"), full_name=f"Chain Voter {i}",
                                 phone_number=f"+2547800{i:05d}")
        tokens.append(str(issue_session(v).uuid_token))

    real_hash = ballot_services._compute_ballot_hash

    def slow(*args, **kwargs):
        time.sleep(0.05)
        return real_hash(*args, **kwargs)

    monkeypatch.setattr(ballot_services, "_compute_ballot_hash", slow)
    barrier = threading.Barrier(N)
    errors = []

    def cast(token, cand):
        try:
            barrier.wait(timeout=10)
            cast_ballot(uuid_token=token, candidate_id=cand.candidate_id)
        except Exception as exc:  # recorded, asserted below
            errors.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=cast, args=(t, cands[i % 2])) for i, t in enumerate(tokens)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)

    assert not errors, errors
    entries = list(AuditLog.objects.order_by("log_id"))
    assert len(entries) == N

    shared = {h: n for h, n in Counter(e.previous_hash for e in entries).items() if n > 1}
    assert not shared, f"{sum(shared.values())} entries share {len(shared)} previous_hash value(s): chain forked"
    expected = ""
    for e in entries:
        assert e.previous_hash == expected, f"log_id {e.log_id} does not link to the entry before it"
        expected = e.ballot_hash
    assert verify_chain_integrity().intact
