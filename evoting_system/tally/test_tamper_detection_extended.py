"""
FR-AUD-02 / FR-P-01 / FR-V-07: the audit integrity check (auditlog.services.verify_chain_integrity, used by
?reverify=1, the auditor "verify chain" page and publish_results) also
  (i)  recomputes every entry's hash from its live ballot row with cast_ballot's own formula, and
  (ii) compares ballots with audit entries per election (a ballot without an entry, an entry without a ballot).
These close tamper scenarios 4, 7, 10 and 13 from C:\\sectest\\results\\tamper_matrix.md, which the link-only
walk did not detect. Real commits; changes made directly in SQL, below the application.
"""

import json
import os
from datetime import timedelta

import psycopg2
import pytest
from django.db import connection
from django.utils import timezone

from auditlog.models import AuditLog
from auditlog.services import verify_chain_integrity
from ballots.models import Ballot
from ballots.services import cast_ballot
from elections.models import Candidate, Election
from tally.crypto import build_tally_proof
from tally.models import ElectionResult
from tally.services import compute_tally, publish_results
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter


def _vote(election, cand, nid):
    v = Voter.objects.create(national_id_hash=sha256_hex(nid), full_name=f"Ext Voter {nid}", phone_number="+2547" + nid)
    return cast_ballot(uuid_token=str(issue_session(v).uuid_token), candidate_id=cand.candidate_id)


def _setup():
    """One PUBLISHED election (5 ballots) and one OPEN, unpublished election (3 ballots), chain intact."""
    now = timezone.now()
    pub = Election.objects.create(title="Ext Published", start_date=now, end_date=now + timedelta(hours=2))
    pub_c = [Candidate.objects.create(election=pub, name=f"Ext P{i}") for i in range(2)]
    pub.open_voting()
    for i in range(5):
        _vote(pub, pub_c[i % 2], f"7900000{i}")
    pub.close_voting()
    publish_results(pub)
    live = Election.objects.create(title="Ext Open", start_date=now, end_date=now + timedelta(hours=2))
    live_c = [Candidate.objects.create(election=live, name=f"Ext O{i}") for i in range(2)]
    live.open_voting()
    for i in range(3):
        _vote(live, live_c[i % 2], f"7910000{i}")
    assert verify_chain_integrity().intact
    return pub, pub_c, live, live_c


def _sql(statement, params):
    with connection.cursor() as cur:
        cur.execute(statement, params)


def _reverify(client, election):
    return client.get(f"/api/tally/{election.election_id}/?reverify=1").json()["verification"]


@pytest.mark.django_db(transaction=True)
def test_fr_aud02_fr_v07_ballot_changed_with_audit_untouched_is_detected(client):
    """Scenario 4: one ballot's candidate changed, audit entry untouched."""
    pub, pub_c, _, _ = _setup()
    ballot = Ballot.objects.filter(election=pub, candidate=pub_c[0]).first()
    entry = AuditLog.objects.get(ballot=ballot)
    _sql("UPDATE ballots_ballot SET candidate_id = %s WHERE ballot_id = %s",
         [str(pub_c[1].candidate_id), str(ballot.ballot_id)])

    result = verify_chain_integrity()
    assert result.intact is False
    assert result.hash_mismatch_log_ids == [entry.log_id]
    assert result.ballots_without_entry == 0
    assert _reverify(client, pub)["chain_currently_intact"] is False


@pytest.mark.django_db(transaction=True)
def test_fr_aud02_extra_ballot_without_audit_entry_is_detected(client):
    """Scenario 7: an extra ballot inserted with no audit entry."""
    pub, pub_c, _, _ = _setup()
    _sql("INSERT INTO ballots_ballot (ballot_id, election_id, candidate_id, created_at) "
         "VALUES (gen_random_uuid(), %s, %s, now())", [str(pub.election_id), str(pub_c[0].candidate_id)])

    result = verify_chain_integrity()
    assert result.intact is False
    assert result.ballots_without_entry == 1
    assert result.hash_mismatch_log_ids == []
    deep = _reverify(client, pub)
    assert deep["chain_currently_intact"] is False
    assert deep["fully_verified"] is False


@pytest.mark.django_db(transaction=True)
def test_fr_aud02_deleted_newest_audit_entry_of_unpublished_election_is_detected():
    """Scenario 10: the newest audit entry (global tail, open unpublished election) deleted."""
    _, _, live, _ = _setup()
    tail = AuditLog.objects.order_by("-log_id").first()
    assert tail.ballot.election_id == live.election_id
    _sql("DELETE FROM auditlog_auditlog WHERE log_id = %s", [tail.log_id])

    result = verify_chain_integrity()
    assert result.intact is False
    assert result.ballots_without_entry == 1


def _restricted_conn():
    """evoting_app connection to this test database (grants re-applied), or None without DB_APP_PASSWORD."""
    if not os.environ.get("DB_APP_PASSWORD"):
        return None
    from auditlog.tests import _restricted_role_connection
    return _restricted_role_connection()


def _rewrite_ballot_and_result(cur, pub, ballot, new_cand):
    """Change one ballot and rewrite the published counts and commitments to match the live ballots,
    with publish_results' own method. Touches only ballots_ballot and tally_electionresult."""
    cur.execute("UPDATE ballots_ballot SET candidate_id = %s WHERE ballot_id = %s",
                [str(new_cand.candidate_id), str(ballot.ballot_id)])
    counts = {str(c.candidate_id): 0 for c in Candidate.objects.filter(election=pub)}
    for b in Ballot.objects.filter(election=pub).exclude(pk=ballot.pk):
        counts[str(b.candidate_id)] += 1
    counts[str(new_cand.candidate_id)] += 1
    total = sum(counts.values())
    p = build_tally_proof(counts, total).to_dict()
    cur.execute(
        "UPDATE tally_electionresult SET candidate_counts = %s, total_ballots = %s, commitment_total_g1 = %s, "
        "commitment_total_g2 = %s, candidate_commitments_g1 = %s WHERE election_id = %s",
        [json.dumps(counts), total, json.dumps(p["commitment_total_g1"]), json.dumps(p["commitment_total_g2"]),
         json.dumps(p["candidate_commitments_g1"]), str(pub.election_id)])


@pytest.mark.django_db(transaction=True)
def test_fr_aud02_fr_db01_consistent_ballot_and_result_rewrite_is_refused_or_detected(client):
    """Scenario 13: change one ballot AND rewrite the published counts and commitments to match, audit untouched.
    As the restricted role evoting_app when DB_APP_PASSWORD is set: the database must refuse it, or it must be
    detected. As the owner (always, or when the restricted role was refused): it must be detected."""
    pub, pub_c, _, _ = _setup()
    ballot = Ballot.objects.filter(election=pub, candidate=pub_c[0]).first()

    app = _restricted_conn()
    app_refused = None
    if app is not None:
        try:
            with app.cursor() as cur:
                cur.execute("BEGIN")
                _rewrite_ballot_and_result(cur, pub, ballot, pub_c[1])
                cur.execute("COMMIT")
            app_refused = False
        except psycopg2.Error as exc:
            app.rollback()
            assert "permission denied" in str(exc).lower(), exc
            app_refused = True
        finally:
            app.close()

    if app_refused is False:  # the restricted role was allowed: it must be detected
        assert Ballot.objects.get(pk=ballot.pk).candidate_id == pub_c[1].candidate_id
    else:  # no restricted role, or it was refused: nothing changed; do it as the owner
        assert Ballot.objects.get(pk=ballot.pk).candidate_id == pub_c[0].candidate_id
        with connection.cursor() as cur:
            _rewrite_ballot_and_result(cur, pub, ballot, pub_c[1])

    # the published tally now matches the live ballots, so only the audit cross-check can catch it
    live = compute_tally(pub)
    assert ElectionResult.objects.get(election=pub).total_ballots == live.total_ballots
    result = verify_chain_integrity()
    assert result.intact is False
    assert result.hash_mismatch_log_ids == [AuditLog.objects.get(ballot=ballot).log_id]
    deep = _reverify(client, pub)
    assert deep["live_counts_match"] is True  # the rewrite is consistent with the ballots
    assert deep["chain_currently_intact"] is False
    assert deep["fully_verified"] is False
