"""
Security-testing finding (Chapter 5.4): GET /api/tally/<id>/ with an id
that matches the router's 36-character lookup pattern but is not a valid
UUID used to raise an unhandled ValidationError (HTTP 500, with a
traceback under DEBUG). It must answer 404 exactly like an unknown
election. Pre-fix capture: C:\\sectest\\results\\finding_api_tally_500.txt
(outside the repo).
"""

import pytest
from django.test import Client


@pytest.fixture
def lenient_client():
    # Return the 500 as a response instead of re-raising it, so a regression
    # shows up as a plain status-code assertion failure.
    return Client(raise_request_exception=False)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "bad_id",
    [
        "a" * 36,                                   # hex letters only, no dashes
        "-" * 36,                                   # dashes only
        "a" * 35 + "-",                             # right charset, 35 hex digits
    ],
)
def test_api_tally_malformed_id_returns_404_not_500(lenient_client, bad_id):
    response = lenient_client.get(f"/api/tally/{bad_id}/")
    assert response.status_code == 404
    assert b"Traceback" not in response.content


@pytest.mark.django_db
def test_api_tally_malformed_id_with_reverify_returns_404(lenient_client):
    response = lenient_client.get(f"/api/tally/{'a' * 36}/?reverify=1")
    assert response.status_code == 404


@pytest.mark.django_db
def test_api_tally_unknown_but_valid_uuid_still_returns_404(lenient_client):
    response = lenient_client.get("/api/tally/00000000-0000-0000-0000-000000000000/")
    assert response.status_code == 404
    assert response.json() == {"detail": "No such election."}
