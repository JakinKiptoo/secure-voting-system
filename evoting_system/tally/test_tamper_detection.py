"""
Tamper detection after publication (FR-P-01 public verification, FR-AUD-02 chain check, FR-V-07 audit
binding). Each test publishes a small election with real commits, changes the database directly with SQL
as the owner role (simulating a compromise below the application), and checks that the change is detected
by ?reverify=1 and/or the audit-chain walk, as established in C:\\sectest\\results\\tamper_matrix.md.
Only detections that hold are tested here; gaps are listed in that matrix, not asserted.
"""

import json
from datetime import timedelta

import pytest
from django.db import IntegrityError, connection
from django.utils import timezone

from auditlog.models import AuditLog
from auditlog.services import verify_chain_integrity
from ballots.models import Ballot
from ballots.services import cast_ballot
from elections.models import Candidate, Election
from tally.models import ElectionResult
from tally.services import publish_results
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter


def _published():
    now = timezone.now()
    election = Election.objects.create(title="Tamper Election", start_date=now, end_date=now + timedelta(hours=2))
    cands = [Candidate.objects.create(election=election, name=f"Tamper Candidate {i}") for i in range(2)]
    election.open_voting()
    for i in range(5):
        voter = Voter.objects.create(national_id_hash=sha256_hex(f"7500000{i}"), full_name=f"Tamper Voter {i}",
                                     phone_number=f"+25475000000{i}")
        cast_ballot(uuid_token=str(issue_session(voter).uuid_token), candidate_id=cands[i % 2].candidate_id)
    election.close_voting()
    publish_results(election)
    assert verify_chain_integrity().intact
    return election, cands


def _sql(statement, params):
    with connection.cursor() as cur:
        cur.execute(statement, params)


def _verification(client, election, reverify):
    query = "?reverify=1" if reverify else ""
    return client.get(f"/api/tally/{election.election_id}/{query}").json()["verification"]


def _bump_one_count(election, change_total):
    result = ElectionResult.objects.get(election=election)
    counts = dict(result.candidate_counts)
    counts[sorted(counts)[0]] += 1
    total = result.total_ballots + (1 if change_total else 0)
    _sql("UPDATE tally_electionresult SET candidate_counts = %s, total_ballots = %s WHERE result_id = %s",
         [json.dumps(counts), total, str(result.result_id)])


@pytest.mark.django_db(transaction=True)
def test_fr_p01_changed_published_count_is_detected(client):
    """Scenario 1: one published candidate count changed, total unchanged."""
    election, _ = _published()
    _bump_one_count(election, change_total=False)

    default = _verification(client, election, reverify=False)
    assert default["aggregation_holds"] is False
    assert default["cryptographic_proof_valid"] is False
    deep = _verification(client, election, reverify=True)
    assert deep["aggregation_holds"] is False
    assert deep["recomputed_commitments_match"] is False
    assert deep["live_counts_match"] is False
    assert deep["fully_verified"] is False


@pytest.mark.django_db(transaction=True)
def test_fr_p01_consistent_change_of_published_total_and_count_is_detected(client):
    """Scenario 2: total and one count changed consistently (they still add up)."""
    election, _ = _published()
    _bump_one_count(election, change_total=True)

    default = _verification(client, election, reverify=False)
    assert default["aggregation_holds"] is True  # the numbers still add up
    assert default["recomputed_commitments_match"] is False
    deep = _verification(client, election, reverify=True)
    assert deep["recomputed_commitments_match"] is False
    assert deep["live_counts_match"] is False
    assert deep["fully_verified"] is False


@pytest.mark.django_db(transaction=True)
def test_fr_p01_ballot_changed_after_publication_is_detected_by_reverify(client):
    """Scenario 4: one ballot's candidate changed to another candidate of the same election."""
    election, cands = _published()
    ballot = Ballot.objects.filter(election=election, candidate=cands[0]).first()
    _sql("UPDATE ballots_ballot SET candidate_id = %s WHERE ballot_id = %s",
         [str(cands[1].candidate_id), str(ballot.ballot_id)])

    deep = _verification(client, election, reverify=True)
    assert deep["live_counts_match"] is False
    assert deep["fully_verified"] is False


@pytest.mark.django_db(transaction=True)
def test_fr_v07_deleting_an_audited_ballot_is_refused_by_the_database():
    """Scenario 5: a ballot that has an audit entry cannot be deleted (foreign key from AuditLog)."""
    election, _ = _published()
    ballot = Ballot.objects.filter(election=election).first()
    with pytest.raises(IntegrityError):
        _sql("DELETE FROM ballots_ballot WHERE ballot_id = %s", [str(ballot.ballot_id)])
    assert Ballot.objects.filter(pk=ballot.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_fr_p01_fr_aud02_ballot_deleted_with_its_audit_entry_is_detected(client):
    """Scenario 5b: a middle ballot deleted together with its audit entry."""
    election, _ = _published()
    entry = list(AuditLog.objects.filter(ballot__election=election).order_by("log_id"))[2]
    ballot_id = str(entry.ballot_id)
    _sql("DELETE FROM auditlog_auditlog WHERE log_id = %s", [entry.log_id])
    _sql("DELETE FROM ballots_ballot WHERE ballot_id = %s", [ballot_id])

    deep = _verification(client, election, reverify=True)
    assert deep["live_counts_match"] is False
    assert deep["audit_entries_unchanged"] is False
    assert deep["chain_currently_intact"] is False
    assert verify_chain_integrity().intact is False


@pytest.mark.django_db(transaction=True)
def test_fr_p01_fr_aud02_altered_audit_hash_is_detected(client):
    """Scenario 8: one audit entry's ballot_hash altered (middle of the chain)."""
    election, _ = _published()
    entry = list(AuditLog.objects.filter(ballot__election=election).order_by("log_id"))[2]
    _sql("UPDATE auditlog_auditlog SET ballot_hash = %s WHERE log_id = %s", ["0" * 64, entry.log_id])

    chain = verify_chain_integrity()
    assert chain.intact is False
    assert chain.break_log_id > entry.log_id  # the next entry no longer links to it
    deep = _verification(client, election, reverify=True)
    assert deep["audit_entries_unchanged"] is False
    assert deep["chain_currently_intact"] is False
    assert deep["fully_verified"] is False


@pytest.mark.django_db(transaction=True)
def test_fr_p01_fr_aud02_deleted_middle_audit_entry_is_detected(client):
    """Scenario 9: one audit entry deleted from the middle of the chain."""
    election, _ = _published()
    entry = list(AuditLog.objects.filter(ballot__election=election).order_by("log_id"))[2]
    _sql("DELETE FROM auditlog_auditlog WHERE log_id = %s", [entry.log_id])

    assert verify_chain_integrity().intact is False
    deep = _verification(client, election, reverify=True)
    assert deep["audit_entries_unchanged"] is False
    assert deep["chain_currently_intact"] is False
    assert deep["fully_verified"] is False
