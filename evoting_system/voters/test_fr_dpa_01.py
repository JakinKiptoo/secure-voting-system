"""
FR-DPA-01 (EXTENSIONS_ROADMAP.md): public privacy notice at collection.

Extension ID, not a core requirement -- tracked in the extension table
of TRACEABILITY.md, never in the core FR/NFR table. Every test name
below carries the ID.
"""

import uuid
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from auditlog.models import AuditLog
from ballots.models import Ballot
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voter_sessions.services import issue_session
from voters.models import Voter, VoterElectionParticipation
from voters.privacy import PRIVACY_NOTICE_CONTROLLER

PRIVACY_URL_NAME = "voters:privacy"


def _context_values(response):
    """All top-level values in the rendered template context, whether Django
    handed back a ContextList (several templates) or a bare context (one
    standalone template, as this page is)."""
    context = response.context
    if hasattr(context, "keys"):
        return {key: context.get(key) for key in context.keys()}
    return context.flatten()


@pytest.mark.django_db
def test_fr_dpa01_privacy_notice_is_reachable_without_login(client):
    response = client.get(reverse(PRIVACY_URL_NAME))

    assert response.status_code == 200
    assert reverse(PRIVACY_URL_NAME) == "/voters/privacy/"


@pytest.mark.django_db
def test_fr_dpa01_privacy_notice_states_prototype_before_everything_else(client):
    body = client.get(reverse(PRIVACY_URL_NAME)).content.decode()

    prototype = body.index("academic prototype that uses test data only")
    assert prototype < body.index("Who is responsible for this data")
    assert prototype < body.index("What is collected, and why")
    # The page itself must not claim legal compliance.
    assert "compliant" not in body.lower()
    assert "not a legal statement" in body


@pytest.mark.django_db
def test_fr_dpa01_privacy_notice_contains_the_key_disclosures(client):
    body = client.get(reverse(PRIVACY_URL_NAME)).content.decode()

    # What is collected.
    for text in (
        "National ID number",
        "SHA-256 hash",
        "Full name",
        "Phone number",
        "One-time passcode",
        "Audit-log entry",
        "Participation record",
    ):
        assert text in body
    # Why.
    assert "one vote per election" in body
    assert "checked for tampering" in body
    # Anonymity.
    assert "no field connecting a ballot to a voter" in body
    # Who can see what.
    for role in ("Anyone (no login)", "Officials", "Auditors", "Administrators"):
        assert role in body
    # Real deployment sentence, naming no electoral body.
    assert "the organising electoral body would be the controller" in body
    assert "act as a processor on its instructions" in body
    assert "IEBC" not in body.split("<main", 1)[1].split("</main>", 1)[0]
    # The visible placeholders are there for the student to fill in.
    assert "[UNIVERSITY EMAIL: to be filled in by the student]" in body
    assert "[TO BE CONFIRMED BY THE PROJECT TEAM]" in body


@pytest.mark.django_db
def test_fr_dpa01_controller_text_comes_from_one_constant(client, monkeypatch):
    """Changing the single constant changes the page: nothing else to edit."""
    monkeypatch.setitem(PRIVACY_NOTICE_CONTROLLER, "controller_line", "CHANGED CONTROLLER LINE")
    monkeypatch.setitem(PRIVACY_NOTICE_CONTROLLER, "contact", "changed.contact@example.test")
    monkeypatch.setitem(PRIVACY_NOTICE_CONTROLLER, "retention", "CHANGED RETENTION")

    body = client.get(reverse(PRIVACY_URL_NAME)).content.decode()

    assert "CHANGED CONTROLLER LINE" in body
    assert "changed.contact@example.test" in body
    assert "CHANGED RETENTION" in body
    assert "Jakin Kipkorir" not in body


def test_fr_dpa01_controller_constant_holds_the_decided_text():
    assert PRIVACY_NOTICE_CONTROLLER["controller_line"] == (
        "Jakin Kipkorir, final-year BBIT project, Strathmore University "
        "School of Computing and Engineering Sciences"
    )
    assert "@" not in PRIVACY_NOTICE_CONTROLLER["contact"]  # placeholder, no real address
    assert PRIVACY_NOTICE_CONTROLLER["contact"].startswith("[")
    assert PRIVACY_NOTICE_CONTROLLER["retention"].startswith("[")


@pytest.mark.django_db
def test_fr_dpa01_registration_page_links_to_notice_above_the_form(client):
    body = client.get(reverse("voters:register")).content.decode()
    link = reverse(PRIVACY_URL_NAME)

    assert link in body
    assert body.index(link) < body.index("<form")


@pytest.mark.django_db
def test_fr_dpa01_credentials_page_and_landing_page_link_to_notice(client):
    link = reverse(PRIVACY_URL_NAME)

    assert link in client.get(reverse("voters:credentials")).content.decode()
    assert link in client.get(reverse("home")).content.decode()


@pytest.mark.django_db
def test_fr_dpa01_no_consent_checkbox_and_forms_unchanged(client):
    for name in ("voters:register", "voters:credentials"):
        body = client.get(reverse(name)).content.decode()
        assert 'type="checkbox"' not in body
    register_form = client.get(reverse("voters:register")).context["form"]
    credentials_form = client.get(reverse("voters:credentials")).context["form"]
    assert list(register_form.fields) == ["national_id", "full_name", "phone_number"]
    assert list(credentials_form.fields) == ["national_id", "phone_number"]


@pytest.mark.django_db
def test_fr_dpa01_notice_renders_no_voter_session_ballot_data(client):
    """Same leak-test pattern as the other public pages: put distinctive
    voter-level data in the database, then prove none of it reaches the
    page or its template context."""
    election = Election.objects.create(
        title="DPA Leak Election",
        start_date=timezone.now(),
        end_date=timezone.now() + timedelta(hours=2),
    )
    candidate = Candidate.objects.create(election=election, name="Leak Candidate Zed")
    election.open_voting()
    voter = Voter.objects.create(
        national_id_hash="leaktesthash0123456789",
        full_name="Zuberi Leaktest Mwangi",
        phone_number="+254799123456",
    )
    session = issue_session(voter)
    ballot = Ballot.objects.create(election=election, candidate=candidate)
    AuditLog.objects.create(ballot=ballot, action_type="ballot_cast", ballot_hash="a" * 64)
    VoterElectionParticipation.objects.create(voter=voter, election=election, has_voted=True)

    response = client.get(reverse(PRIVACY_URL_NAME))
    body = response.content.decode()

    for secret in (
        "Zuberi Leaktest Mwangi",
        "+254799123456",
        "leaktesthash0123456789",
        str(voter.voter_id),
        str(session.uuid_token),
        str(ballot.ballot_id),
        "Leak Candidate Zed",
        "DPA Leak Election",
        "a" * 64,
    ):
        assert secret not in body

    for key, value in _context_values(response).items():
        assert not isinstance(value, (Voter, Session, Ballot, AuditLog, VoterElectionParticipation)), key
        assert not isinstance(value, uuid.UUID), key


@pytest.mark.django_db
def test_fr_dpa01_notice_performs_no_database_writes(client):
    with CaptureQueriesContext(connection) as queries:
        assert client.get(reverse(PRIVACY_URL_NAME)).status_code == 200

    writes = [
        q["sql"] for q in queries.captured_queries
        if q["sql"].lstrip().split(None, 1)[0].upper() in {"INSERT", "UPDATE", "DELETE"}
    ]
    assert writes == []


@pytest.mark.django_db
def test_fr_dpa01_notice_rejects_post_put_patch_delete(client):
    url = reverse(PRIVACY_URL_NAME)
    before = (Voter.objects.count(), Session.objects.count(), AuditLog.objects.count(), Ballot.objects.count())

    assert client.post(url, {"full_name": "x"}).status_code == 405
    assert client.put(url, {}).status_code == 405
    assert client.patch(url, {}).status_code == 405
    assert client.delete(url).status_code == 405

    assert before == (Voter.objects.count(), Session.objects.count(), AuditLog.objects.count(), Ballot.objects.count())


@pytest.mark.django_db
def test_fr_dpa01_notice_contains_no_form(client):
    body = client.get(reverse(PRIVACY_URL_NAME)).content.decode()

    assert "<form" not in body
    assert "csrfmiddlewaretoken" not in body


def test_fr_dpa01_dpa_checklist_item_7_cites_the_new_view():
    from auditors.dpa_checklist import DPA_CHECKLIST

    item = next(i for i in DPA_CHECKLIST if i["number"] == 7)
    assert item["status"] == "met"
    assert "voters/views.py::privacy_notice_view" in item["component"]
    assert "templates/voters/privacy_notice.html" in item["component"]
    # Item 8 (data-subject self-service) stays unmet: out of scope.
    assert next(i for i in DPA_CHECKLIST if i["number"] == 8)["status"] == "not_met"
