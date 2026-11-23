"""
Public tally API is JSON only (security-run follow-up): a browser asking
for HTML must get JSON, never DRF's browsable API page, which printed the
view's internal docstring. The JSON body itself must be unchanged.
"""

from datetime import timedelta

import pytest
from django.utils import timezone

from ballots.services import cast_ballot
from elections.models import Candidate, Election
from tally.services import publish_results
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

EXPECTED_KEYS = [
    "available",
    "election_id",
    "election_title",
    "election_status",
    "reason_unavailable",
    "total_ballots",
    "candidate_results",
    "published_at",
    "proof",
    "verification",
    "audit_entries",
]
FORBIDDEN_KEY_PARTS = ("voter", "session", "national_id")
BROWSER_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


def _published_election():
    now = timezone.now()
    election = Election.objects.create(
        title="JSON Only Election", start_date=now, end_date=now + timedelta(hours=2)
    )
    candidate = Candidate.objects.create(election=election, name="JSON Only Candidate")
    election.open_voting()
    voter = Voter.objects.create(
        national_id_hash=sha256_hex("77776666"), full_name="Json Voter", phone_number="+254777766660"
    )
    cast_ballot(uuid_token=str(issue_session(voter).uuid_token), candidate_id=candidate.candidate_id)
    election.close_voting()
    publish_results(election)
    return election


def _all_keys(value, path="$"):
    if isinstance(value, dict):
        for k, v in value.items():
            yield f"{path}.{k}", k
            yield from _all_keys(v, f"{path}.{k}")
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _all_keys(v, f"{path}[{i}]")


@pytest.mark.django_db
@pytest.mark.parametrize("query", ["", "?reverify=1"])
def test_api_tally_browser_accept_html_gets_json_not_browsable_api(client, query):
    election = _published_election()
    response = client.get(f"/api/tally/{election.election_id}/{query}", HTTP_ACCEPT=BROWSER_ACCEPT)
    assert response.status_code == 200
    assert response["Content-Type"].startswith("application/json")
    body = response.content.decode()
    assert not body.lstrip().startswith("<")
    assert "services.py" not in body
    assert "sprint" not in body.lower()
    response.json()  # parses as JSON


@pytest.mark.django_db
def test_api_tally_explicit_html_only_request_is_not_served_html(client):
    election = _published_election()
    response = client.get(f"/api/tally/{election.election_id}/", HTTP_ACCEPT="text/html")
    # JSONRenderer cannot satisfy a text/html-only request: DRF answers 406
    # with a JSON error body, never an HTML page.
    assert response.status_code == 406
    assert response["Content-Type"].startswith("application/json")


@pytest.mark.django_db
def test_api_tally_format_api_query_param_does_not_select_browsable_api(client):
    election = _published_election()
    response = client.get(f"/api/tally/{election.election_id}/?format=api")
    assert response.status_code == 404  # no renderer for format "api"
    assert not response.content.decode().lstrip().startswith("<!DOCTYPE")


@pytest.mark.django_db
def test_api_tally_json_keys_unchanged_and_no_identity_fields(client):
    election = _published_election()
    data = client.get(f"/api/tally/{election.election_id}/?reverify=1").json()
    assert list(data.keys()) == EXPECTED_KEYS
    assert data["available"] is True and data["total_ballots"] == 1
    offenders = [p for p, k in _all_keys(data) if any(f in k.lower() for f in FORBIDDEN_KEY_PARTS)]
    assert offenders == []
