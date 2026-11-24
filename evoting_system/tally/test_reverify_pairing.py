"""
FR-P-01/FR-P-02, NFR-PE-01: the public tally API and results page run
the expensive pairing check (crypto.verify_tally_proof) only with
?reverify=1. The default request runs the cheap commitment checks only
and reports the pairing as not run (pairing_holds None, deep_verified
False). Tampering with a published result is still detected.
"""

from datetime import timedelta
from unittest import mock

import pytest
from django.urls import reverse
from django.utils import timezone

from ballots.services import cast_ballot
from elections.models import Candidate, Election
from tally import crypto, services
from tally.models import ElectionResult
from tally.services import publish_results
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

EXPECTED_KEYS = [
    "available", "election_id", "election_title", "election_status", "reason_unavailable",
    "total_ballots", "candidate_results", "published_at", "proof", "verification", "audit_entries",
]
FORBIDDEN_KEY_PARTS = ("voter", "session", "national_id")


def _published_election():
    now = timezone.now()
    election = Election.objects.create(title="Pairing Election", start_date=now, end_date=now + timedelta(hours=2))
    cands = [Candidate.objects.create(election=election, name=f"Pairing Candidate {i}") for i in range(2)]
    election.open_voting()
    for i, nid in enumerate(("74000001", "74000002", "74000003")):
        voter = Voter.objects.create(national_id_hash=sha256_hex(nid), full_name=f"Pairing Voter {i}",
                                     phone_number=f"+25474000000{i}")
        cast_ballot(uuid_token=str(issue_session(voter).uuid_token), candidate_id=cands[i % 2].candidate_id)
    election.close_voting()
    publish_results(election)
    return election


def _api(client, election, query=""):
    return client.get(f"/api/tally/{election.election_id}/{query}").json()


def _all_keys(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from _all_keys(v)
    elif isinstance(value, list):
        for v in value:
            yield from _all_keys(v)


@pytest.mark.django_db
def test_fr_p01_default_api_request_does_not_run_the_pairing_check(client):
    election = _published_election()
    with mock.patch.object(services, "verify_tally_proof", wraps=crypto.verify_tally_proof) as spy:
        data = _api(client, election)
    spy.assert_not_called()
    v = data["verification"]
    assert v["deep_verified"] is False
    assert v["pairing_holds"] is None
    assert v["cryptographic_proof_valid"] is None
    assert v["aggregation_holds"] is True
    assert v["recomputed_commitments_match"] is True


@pytest.mark.django_db
def test_fr_p02_default_results_page_does_not_run_the_pairing_check(client):
    election = _published_election()
    with mock.patch.object(services, "verify_tally_proof", wraps=crypto.verify_tally_proof) as spy:
        response = client.get(reverse("tally:verify", args=[election.election_id]))
    spy.assert_not_called()
    body = response.content.decode()
    assert response.status_code == 200
    assert "The pairing check itself was not re-run for this page load" in body
    assert "FAILED" not in body


@pytest.mark.django_db
@pytest.mark.parametrize("path", ["api", "page"])
def test_fr_p01_reverify_runs_the_pairing_check_once_with_the_same_result(client, path):
    election = _published_election()
    result = ElectionResult.objects.get(election=election)
    stored = crypto.TallyProof.from_dict({
        "total_ballots": result.total_ballots, "candidate_counts": result.candidate_counts,
        "commitment_total_g1": result.commitment_total_g1, "commitment_total_g2": result.commitment_total_g2,
        "candidate_commitments_g1": result.candidate_commitments_g1,
    })
    direct = crypto.verify_tally_proof(stored)

    with mock.patch.object(services, "verify_tally_proof", wraps=crypto.verify_tally_proof) as spy:
        if path == "api":
            v = _api(client, election, "?reverify=1")["verification"]
        else:
            response = client.get(reverse("tally:verify", args=[election.election_id]), {"reverify": "1"})
            v = response.context["payload"].verification
            assert "fully verified" in response.content.decode().lower()
    assert spy.call_count == 1
    assert v["deep_verified"] is True
    assert v["pairing_holds"] is direct.pairing_holds is True
    assert v["aggregation_holds"] is direct.aggregation_holds is True
    assert v["recomputed_commitments_match"] is direct.recomputed_commitments_match is True
    assert v["cryptographic_proof_valid"] is direct.valid is True
    assert v["fully_verified"] is True


@pytest.mark.django_db
def test_fr_p01_tampered_published_tally_is_detected_with_reverify(client):
    election = _published_election()
    result = ElectionResult.objects.get(election=election)
    tampered = dict(result.candidate_counts)
    first = sorted(tampered)[0]
    tampered[first] += 5  # published counts no longer match the commitments or the ballots
    ElectionResult.objects.filter(pk=result.pk).update(candidate_counts=tampered)

    v = _api(client, election, "?reverify=1")["verification"]
    assert v["cryptographic_proof_valid"] is False
    assert v["aggregation_holds"] is False
    assert v["recomputed_commitments_match"] is False
    assert v["live_counts_match"] is False
    assert v["fully_verified"] is False

    # The cheap checks on the default path flag it too.
    d = _api(client, election)["verification"]
    assert d["deep_verified"] is False
    assert d["aggregation_holds"] is False
    assert d["cryptographic_proof_valid"] is False


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", "?reverify=1"])
def test_fr_p01_keys_unchanged_and_no_identity_fields(client, query):
    election = _published_election()
    data = _api(client, election, query)
    assert list(data.keys()) == EXPECTED_KEYS
    offenders = [k for k in _all_keys(data) if any(f in k.lower() for f in FORBIDDEN_KEY_PARTS)]
    assert offenders == []
