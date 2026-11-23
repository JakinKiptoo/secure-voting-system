"""
FR-OFF-06 (EXTENSIONS_ROADMAP.md): "Publish results" link on the Officials
Elections list and results page. Extension ID, not a core requirement.

The link only navigates to the existing tally:publish confirmation page;
publishing itself stays the existing POST in tally/views.py. Every test
name carries the ID.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from elections.models import Candidate, Election
from tally.models import ElectionResult
from tally.services import publish_results

from .permissions import OFFICIAL_GROUP_NAME

ELECTIONS_URL = "officials:elections"
RESULTS_URL = "officials:results"
PUBLISH_URL_NAME = "tally:publish"


def _login_official(client, django_user_model):
    user = django_user_model.objects.create_user(username="off06", password="pass12345", is_staff=True)
    group, _ = Group.objects.get_or_create(name=OFFICIAL_GROUP_NAME)
    user.groups.add(group)
    client.force_login(user)


def _election(title, state):
    """state: DRAFT | OPEN | CLOSED | PUBLISHED. Candidates are created
    while DRAFT (FR-A-04), then the real open/close transitions are used."""
    election = Election.objects.create(
        title=title, start_date=timezone.now(), end_date=timezone.now() + timedelta(hours=2)
    )
    Candidate.objects.create(election=election, name=f"{title} Candidate")
    if state in ("OPEN", "CLOSED", "PUBLISHED"):
        election.open_voting()
    if state in ("CLOSED", "PUBLISHED"):
        election.close_voting()
    if state == "PUBLISHED":
        publish_results(election)
    return election


def _publish_href(election):
    return reverse(PUBLISH_URL_NAME, args=[election.election_id])


@pytest.mark.django_db
def test_fr_off06_elections_list_shows_publish_link_for_closed_unpublished(client, django_user_model):
    _login_official(client, django_user_model)
    election = _election("Closed Unpublished", "CLOSED")

    body = client.get(reverse(ELECTIONS_URL)).content.decode()

    assert f'href="{_publish_href(election)}"' in body
    assert "Publish results" in body


@pytest.mark.django_db
def test_fr_off06_elections_list_hides_publish_link_for_draft_open_and_published(client, django_user_model):
    _login_official(client, django_user_model)
    others = [_election("Draft One", "DRAFT"), _election("Open One", "OPEN"), _election("Published One", "PUBLISHED")]

    response = client.get(reverse(ELECTIONS_URL))
    body = response.content.decode()

    assert response.status_code == 200
    for election in others:
        assert _publish_href(election) not in body
    assert "Publish results" not in body
    # The existing link for a published CLOSED election is unchanged.
    published = others[2]
    assert f'href="{reverse("officials:results", args=[published.election_id])}"' in body


@pytest.mark.django_db
def test_fr_off06_elections_list_link_is_per_row(client, django_user_model):
    _login_official(client, django_user_model)
    unpublished = _election("Needs Publishing", "CLOSED")
    published = _election("Already Published", "PUBLISHED")

    body = client.get(reverse(ELECTIONS_URL)).content.decode()

    assert _publish_href(unpublished) in body
    assert _publish_href(published) not in body


@pytest.mark.django_db
def test_fr_off06_link_target_is_the_existing_tally_publish_url(client, django_user_model):
    _login_official(client, django_user_model)
    election = _election("Target Check", "CLOSED")

    assert _publish_href(election) == f"/tally/{election.election_id}/publish/"
    # The target is the existing confirmation page: GET renders it, a GET
    # alone publishes nothing.
    assert client.get(_publish_href(election)).status_code == 200
    assert not ElectionResult.objects.filter(election=election).exists()


@pytest.mark.django_db
def test_fr_off06_results_page_shows_publish_link_when_closed_unpublished(client, django_user_model):
    _login_official(client, django_user_model)
    election = _election("Results Unpublished", "CLOSED")

    body = client.get(reverse(RESULTS_URL, args=[election.election_id])).content.decode()

    assert "Results not yet published" in body
    assert f'href="{_publish_href(election)}"' in body


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["DRAFT", "OPEN", "PUBLISHED"])
def test_fr_off06_results_page_hides_publish_link_for_draft_open_published(client, django_user_model, state):
    _login_official(client, django_user_model)
    election = _election(f"Results {state}", state)

    response = client.get(reverse(RESULTS_URL, args=[election.election_id]))

    assert response.status_code == 200
    assert _publish_href(election) not in response.content.decode()
    assert "Publish results" not in response.content.decode()


@pytest.mark.django_db
def test_fr_off06_viewing_pages_never_publishes_anything(client, django_user_model):
    _login_official(client, django_user_model)
    election = _election("No Side Effects", "CLOSED")

    client.get(reverse(ELECTIONS_URL))
    client.get(reverse(RESULTS_URL, args=[election.election_id]))

    assert ElectionResult.objects.count() == 0


@pytest.mark.django_db
def test_fr_off06_elections_page_uses_one_query_for_published_state(client, django_user_model):
    """The published check is one query for the whole page, not one per row."""
    _login_official(client, django_user_model)
    for i in range(4):
        _election(f"Row {i}", "CLOSED")

    with CaptureQueriesContext(connection) as queries:
        assert client.get(reverse(ELECTIONS_URL)).status_code == 200

    result_queries = [q for q in queries.captured_queries if "tally_electionresult" in q["sql"]]
    assert len(result_queries) == 1


@pytest.mark.django_db
def test_fr_off06_publish_page_still_needs_the_existing_role(client, django_user_model):
    """Showing the link grants nothing: the target keeps its own permission."""
    election = _election("Perm Check", "CLOSED")

    anonymous = client.get(_publish_href(election))
    assert anonymous.status_code == 302 and "/admin/login/" in anonymous["Location"]

    plain_staff = django_user_model.objects.create_user(username="plain", password="x12345678", is_staff=True)
    client.force_login(plain_staff)
    assert client.get(_publish_href(election)).status_code == 403
