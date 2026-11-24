"""
NFR-PE-01 / FR-P-01: the public ?reverify=1 request cannot be repeated to run the
expensive pairing check (crypto.verify_tally_proof) on every call. Its result is
cached for tally.services.PAIRING_CACHE_SECONDS, keyed on the published proof's
own fields, and a cached result is marked with verification["pairing_cached_at"].
The default request (no pairing check) is unchanged.
"""

import json
import time
from datetime import timedelta
from unittest import mock

import pytest
from django.core.cache import cache
from django.db import connection
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


@pytest.fixture(autouse=True)
def empty_cache():
    cache.clear()
    yield
    cache.clear()


def _published():
    now = timezone.now()
    election = Election.objects.create(title="Cache Election", start_date=now, end_date=now + timedelta(hours=2))
    cands = [Candidate.objects.create(election=election, name=f"Cache Candidate {i}") for i in range(2)]
    election.open_voting()
    for i in range(3):
        v = Voter.objects.create(national_id_hash=sha256_hex(f"7700000{i}"), full_name=f"Cache Voter {i}",
                                 phone_number=f"+25477000000{i}")
        cast_ballot(uuid_token=str(issue_session(v).uuid_token), candidate_id=cands[i % 2].candidate_id)
    election.close_voting()
    publish_results(election)
    return election


def _reverify(client, election):
    return client.get(f"/api/tally/{election.election_id}/?reverify=1").json()["verification"]


@pytest.mark.django_db
def test_nfr_pe01_default_request_is_unaffected_by_the_reverify_cache(client):
    election = _published()
    with mock.patch.object(services, "verify_tally_proof", wraps=crypto.verify_tally_proof) as spy:
        for _ in range(3):
            v = client.get(f"/api/tally/{election.election_id}/").json()["verification"]
            assert v["deep_verified"] is False
            assert v["pairing_holds"] is None
            assert "pairing_cached_at" not in v
    spy.assert_not_called()


@pytest.mark.django_db
def test_nfr_pe01_repeated_reverify_runs_the_pairing_check_once_and_says_cached(client):
    election = _published()
    with mock.patch.object(services, "verify_tally_proof", wraps=crypto.verify_tally_proof) as spy:
        first = _reverify(client, election)
        second = _reverify(client, election)
        third = _reverify(client, election)
        page = client.get(reverse("tally:verify", args=[election.election_id]), {"reverify": "1"})
    assert spy.call_count == 1
    assert first["pairing_cached_at"] is None
    assert second["pairing_cached_at"] is not None
    assert third["pairing_cached_at"] == second["pairing_cached_at"]
    for v in (first, second, third):
        assert v["pairing_holds"] is True and v["cryptographic_proof_valid"] is True and v["fully_verified"] is True
    assert "Cached result: this pairing check ran at" in page.content.decode()


@pytest.mark.django_db
def test_nfr_pe01_fr_p01_cached_reverify_result_is_not_reused_after_the_tally_changes(client):
    election = _published()
    with mock.patch.object(services, "verify_tally_proof", wraps=crypto.verify_tally_proof) as spy:
        before = _reverify(client, election)
        assert before["cryptographic_proof_valid"] is True

        result = ElectionResult.objects.get(election=election)
        counts = dict(result.candidate_counts)
        counts[sorted(counts)[0]] += 1
        with connection.cursor() as cur:
            cur.execute("UPDATE tally_electionresult SET candidate_counts = %s WHERE result_id = %s",
                        [json.dumps(counts), str(result.result_id)])

        after = _reverify(client, election)
    assert spy.call_count == 2
    assert after["pairing_cached_at"] is None
    assert after["aggregation_holds"] is False
    assert after["cryptographic_proof_valid"] is False
    assert after["fully_verified"] is False


@pytest.mark.django_db
def test_nfr_pe01_reverify_cache_expires(client, monkeypatch):
    monkeypatch.setattr(services, "PAIRING_CACHE_SECONDS", 1)
    election = _published()
    with mock.patch.object(services, "verify_tally_proof", wraps=crypto.verify_tally_proof) as spy:
        _reverify(client, election)
        time.sleep(1.5)
        v = _reverify(client, election)
    assert spy.call_count == 2
    assert v["pairing_cached_at"] is None
