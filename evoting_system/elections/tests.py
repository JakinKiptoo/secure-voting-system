from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from .models import Candidate, Election


def _make_election(**overrides):
    now = timezone.now()
    defaults = {
        "title": "2027 Student Council Election",
        "start_date": now,
        "end_date": now + timedelta(days=1),
    }
    defaults.update(overrides)
    return Election.objects.create(**defaults)


@pytest.mark.django_db
def test_fr_a01_election_creation():
    """Smoke test only: confirms Election can be created (FR-A-01)."""
    election = _make_election()

    assert election.election_id is not None
    assert election.status == Election.Status.DRAFT


@pytest.mark.django_db
def test_fr_a02_candidate_creation():
    """Smoke test only: confirms Candidate can be created against an Election (FR-A-02)."""
    election = _make_election()
    candidate = Candidate.objects.create(
        election=election,
        name="Amina Yusuf",
        party="Independent",
        biography="Third-year student.",
    )

    assert candidate.candidate_id is not None
    assert candidate.election == election


@pytest.mark.django_db
def test_fr_a03_open_voting_transitions_draft_to_open():
    election = _make_election()
    election.open_voting()
    election.refresh_from_db()
    assert election.status == Election.Status.OPEN


@pytest.mark.django_db
def test_fr_a03_open_voting_rejects_non_draft_election():
    election = _make_election()
    election.open_voting()

    with pytest.raises(ValidationError):
        election.open_voting()  # already OPEN -- can't open again

    election.refresh_from_db()
    assert election.status == Election.Status.OPEN  # unchanged


@pytest.mark.django_db
def test_fr_a03_close_voting_transitions_open_to_closed():
    election = _make_election()
    election.open_voting()
    election.close_voting()
    election.refresh_from_db()
    assert election.status == Election.Status.CLOSED


@pytest.mark.django_db
def test_fr_a03_close_voting_rejects_draft_election():
    election = _make_election()

    with pytest.raises(ValidationError):
        election.close_voting()  # still DRAFT -- can't close what never opened

    election.refresh_from_db()
    assert election.status == Election.Status.DRAFT


@pytest.mark.django_db
def test_fr_a04_candidate_locked_once_election_open():
    """FR-A-04: candidates can't be added once the election is OPEN."""
    election = _make_election()
    Candidate.objects.create(election=election, name="Amina Yusuf")  # fine, still DRAFT

    election.open_voting()

    with pytest.raises(ValidationError):
        Candidate.objects.create(election=election, name="Late Entrant")


@pytest.mark.django_db
def test_fr_a04_candidate_edit_locked_once_election_open():
    """FR-A-04: an existing candidate can't be modified once the election is OPEN."""
    election = _make_election()
    candidate = Candidate.objects.create(election=election, name="Amina Yusuf")

    election.open_voting()
    candidate.name = "Amina Yusuf Hassan"

    with pytest.raises(ValidationError):
        candidate.save()


def _admin_client(client, django_user_model):
    admin_user = django_user_model.objects.create_superuser(
        username="admin", email="admin@example.com", password="adminpass123"
    )
    client.force_login(admin_user)
    return client


@pytest.mark.django_db
def test_admin_status_field_is_read_only_on_change_form(client, django_user_model):
    """
    Regression test (bug fix): the Election admin's change form must
    render `status` as read-only, not a submittable dropdown. Checked
    two ways: (1) the rendered form has no <select name="status">
    control, and (2) actually POSTing a different status value through
    the change form does NOT change it in the database -- the
    read-only field is simply excluded from the submitted ModelForm,
    so Django ignores whatever value a crafted POST includes for it.
    """
    _admin_client(client, django_user_model)
    election = _make_election()
    url = reverse("admin:elections_election_change", args=[election.pk])

    get_response = client.get(url)
    assert get_response.status_code == 200
    assert 'name="status"' not in get_response.content.decode()

    post_data = {
        "title": election.title,
        "start_date_0": election.start_date.date().isoformat(),
        "start_date_1": election.start_date.time().isoformat(),
        "end_date_0": election.end_date.date().isoformat(),
        "end_date_1": election.end_date.time().isoformat(),
        "status": Election.Status.CLOSED,  # attempted direct edit, should be ignored
        "candidates-TOTAL_FORMS": "0",
        "candidates-INITIAL_FORMS": "0",
        "candidates-MIN_NUM_FORMS": "0",
        "candidates-MAX_NUM_FORMS": "1000",
    }
    post_response = client.post(url, post_data)
    assert post_response.status_code in (200, 302)

    election.refresh_from_db()
    assert election.status == Election.Status.DRAFT  # unchanged by the direct POST


@pytest.mark.django_db
def test_admin_open_voting_action_transitions_status(client, django_user_model):
    """FR-A-03 via the admin: the "Open voting" action actually transitions a DRAFT election."""
    _admin_client(client, django_user_model)
    election = _make_election()
    changelist_url = reverse("admin:elections_election_changelist")

    response = client.post(
        changelist_url,
        {
            "action": "open_elections",
            "_selected_action": [str(election.pk)],
        },
        follow=True,
    )

    assert response.status_code == 200
    election.refresh_from_db()
    assert election.status == Election.Status.OPEN


@pytest.mark.django_db
def test_admin_open_voting_action_on_already_open_election_shows_error_not_500(
    client, django_user_model
):
    """
    Bug-adjacent regression test: triggering "Open voting" on an
    election that's already OPEN must surface open_voting()'s
    ValidationError as an admin error message (level=messages.ERROR),
    not crash with a 500 -- and must leave status unchanged.
    """
    _admin_client(client, django_user_model)
    election = _make_election()
    election.open_voting()
    changelist_url = reverse("admin:elections_election_changelist")

    response = client.post(
        changelist_url,
        {
            "action": "open_elections",
            "_selected_action": [str(election.pk)],
        },
        follow=True,
    )

    assert response.status_code == 200  # not a 500
    messages_list = [str(m) for m in response.context["messages"]]
    assert any("only a draft election can be opened" in m.lower() for m in messages_list)

    election.refresh_from_db()
    assert election.status == Election.Status.OPEN  # unchanged, still OPEN not CLOSED/broken
