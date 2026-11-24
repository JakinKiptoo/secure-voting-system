"""
Concurrent double-submit tests for the ballot-casting transaction
(FR-V-04 to FR-V-07), in the style of
voters/test_fr_ses04.py::test_fr_ses04_parallel_wrong_attempts_never_exceed_limit.

Each thread calls ballots.services.cast_ballot on its own database
connection (transaction=True, real commits), all released together by a
barrier. The audit-hash step is slowed by 50 ms so the transaction holds
its locks long enough for the other threads to arrive while it is open.
"""

import threading
import time
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from auditlog.models import AuditLog
from ballots import services as ballot_services
from ballots.models import Ballot
from ballots.services import BallotCastError, cast_ballot
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter, VoterElectionParticipation

N = 10


def _setup(candidates=1):
    now = timezone.now()
    election = Election.objects.create(title="Concurrency Election", start_date=now, end_date=now + timedelta(hours=2))
    cands = [Candidate.objects.create(election=election, name=f"Concurrency Candidate {i}") for i in range(candidates)]
    election.open_voting()
    voter = Voter.objects.create(
        national_id_hash=sha256_hex("72000001"), full_name="Concurrent Voter", phone_number="+254720000001"
    )
    return election, cands, voter


def _slow_audit_step(monkeypatch):
    real = ballot_services._compute_ballot_hash

    def slow(*args, **kwargs):
        time.sleep(0.05)
        return real(*args, **kwargs)

    monkeypatch.setattr(ballot_services, "_compute_ballot_hash", slow)


def _fire(jobs):
    """jobs: list of (token, candidate_id). Returns (successes, rejections, errors)."""
    barrier = threading.Barrier(len(jobs))
    ok, rejected, errors = [], [], []

    def run(token, candidate_id):
        try:
            barrier.wait(timeout=10)
            ok.append(cast_ballot(uuid_token=token, candidate_id=candidate_id))
        except BallotCastError as exc:
            rejected.append(str(exc))
        except Exception as exc:  # recorded, asserted below
            errors.append(repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=job) for job in jobs]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return ok, rejected, errors


@pytest.mark.django_db(transaction=True)
def test_fr_v04_v05_v06_v07_concurrent_submissions_of_one_token_record_one_ballot(monkeypatch):
    election, (candidate,), voter = _setup()
    session = issue_session(voter)
    _slow_audit_step(monkeypatch)

    ok, rejected, errors = _fire([(str(session.uuid_token), candidate.candidate_id)] * N)

    assert not errors, errors
    assert len(ok) == 1
    assert len(rejected) == N - 1
    assert set(rejected) == {"Your session is invalid or has expired. Please log in again."}
    assert Ballot.objects.filter(election=election).count() == 1
    assert AuditLog.objects.filter(ballot__election=election).count() == 1
    assert VoterElectionParticipation.objects.filter(voter=voter, election=election).count() == 1
    assert VoterElectionParticipation.objects.get(voter=voter, election=election).has_voted is True
    voter.refresh_from_db()
    assert voter.has_voted is True
    assert Session.objects.get(pk=session.pk).is_active is False


@pytest.mark.django_db(transaction=True)
def test_fr_v04_v06_concurrent_submissions_one_voter_different_tokens_and_candidates_record_one_ballot(monkeypatch):
    """One voter logged in N times (N live tokens) submits N different
    choices at once in the same election: exactly one Ballot."""
    election, cands, voter = _setup(candidates=3)
    tokens = [str(issue_session(voter).uuid_token) for _ in range(N)]
    _slow_audit_step(monkeypatch)

    ok, rejected, errors = _fire([(tokens[i], cands[i % 3].candidate_id) for i in range(N)])

    assert not errors, errors
    assert len(ok) == 1
    assert len(rejected) == N - 1
    assert set(rejected) == {"This voter has already cast a ballot in this election."}
    assert Ballot.objects.filter(election=election).count() == 1
    assert AuditLog.objects.filter(ballot__election=election).count() == 1
    assert VoterElectionParticipation.objects.filter(voter=voter, election=election).count() == 1
    assert Session.objects.filter(voter=voter, is_active=False).count() == 1
