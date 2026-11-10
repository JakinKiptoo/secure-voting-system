"""
FR-EL-06 Phase 2 (EXTENSIONS_ROADMAP.md) regression tests.

Phase 1 (ballots/test_fr_el_06_investigation.py) only observed the gap
-- it stays as-is, documenting the original investigation, and is not
touched or extended here. These tests prove the Phase 2 fix (the
election-selection step in ballots/views.py::cast_ballot_view) actually
closes that gap, without regressing the single-open-election common
case covered by ballots/tests.py.

Direction taken and why (full reasoning in cast_ballot_view's own
docstring): REQUIREMENTS.md/CLAUDE.md/SCHEMA.md/DIAGRAMS.md contain no
invariant restricting Elections to one OPEN at a time, and the
officials Elections view (FR-OFF-04) already treats multiple
simultaneous elections of any status as normal -- so multiple OPEN
elections are a legitimate state, and the fix is giving the voter an
explicit choice, not a new model-level guard forbidding it.
"""

from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from ballots.models import Ballot
from elections.models import Candidate, Election
from voters.crypto_utils import sha256_hex
from voters.models import Voter

CAST_URL_NAME = "ballots:cast"


def _draft_election(title, days_offset=0):
    now = timezone.now() + timedelta(days=days_offset)
    return Election.objects.create(title=title, start_date=now, end_date=now + timedelta(hours=2))


def _authenticate_via_real_flow(client, monkeypatch, national_id, phone_number):
    """
    Same pattern as ballots/tests.py::test_fr_v04_...full_flow_through_view
    -- goes through the real voters:credentials -> voters:verify_otp
    flow via the Django test client, so `client.session` ends up
    holding a real voting token issued by the real authentication
    view, not a token fabricated directly in the test.
    """
    from voters import views as voters_views

    captured = {}
    monkeypatch.setattr(
        voters_views.sms_gateway,
        "send_otp",
        lambda phone_number, otp: captured.setdefault("otp", otp) or True,
    )

    Voter.objects.create(
        national_id_hash=sha256_hex(national_id),
        full_name="FR-EL-06 Fix Test Voter",
        phone_number=phone_number,
    )
    client.post(reverse("voters:credentials"), {"national_id": national_id, "phone_number": phone_number})
    client.post(reverse("voters:verify_otp"), {"otp": captured["otp"]})
    assert "voting_token" in client.session


# ---------------------------------------------------------------------
# Common case (<=1 OPEN election): byte-for-byte unchanged behavior.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_zero_open_elections_still_shows_no_election_message_not_chooser(client, monkeypatch):
    _authenticate_via_real_flow(client, monkeypatch, "81000001", "+254781000001")

    response = client.get(reverse(CAST_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert "no election currently open" in body.lower()
    # Not the chooser template's own copy:
    assert "more than one election is open" not in body.lower()


@pytest.mark.django_db
def test_single_open_election_shows_ballot_form_directly_no_chooser(client, monkeypatch):
    election = _draft_election("Single Open Election")
    candidate = Candidate.objects.create(election=election, name="Only Candidate")
    election.open_voting()

    _authenticate_via_real_flow(client, monkeypatch, "81000002", "+254781000002")

    response = client.get(reverse(CAST_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert candidate.name in body
    assert "more than one election is open" not in body.lower()
    assert response.context["election"].pk == election.pk


# ---------------------------------------------------------------------
# The actual gap: >1 OPEN election.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_multiple_open_elections_shows_chooser_not_a_ballot_form(client, monkeypatch):
    election_a = _draft_election("Election A")
    election_b = _draft_election("Election B")
    Candidate.objects.create(election=election_a, name="Candidate A1")
    Candidate.objects.create(election=election_b, name="Candidate B1")
    election_a.open_voting()
    election_b.open_voting()

    _authenticate_via_real_flow(client, monkeypatch, "81000003", "+254781000003")

    response = client.get(reverse(CAST_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert "more than one election is open" in body.lower()
    assert election_a.title in body
    assert election_b.title in body
    # The chooser must not also render a ballot form/candidate radios --
    # confirms this is genuinely a step BEFORE the ballot form, not the
    # ballot form with extra content bolted on.
    assert "candidate" not in response.context


@pytest.mark.django_db
def test_choosing_one_election_shows_only_its_own_candidates(client, monkeypatch):
    election_a = _draft_election("Election A")
    election_b = _draft_election("Election B")
    candidate_a = Candidate.objects.create(election=election_a, name="Candidate A1")
    candidate_b = Candidate.objects.create(election=election_b, name="Candidate B1")
    election_a.open_voting()
    election_b.open_voting()

    _authenticate_via_real_flow(client, monkeypatch, "81000004", "+254781000004")

    response = client.get(reverse(CAST_URL_NAME), {"election": str(election_b.election_id)})
    body = response.content.decode()

    assert response.status_code == 200
    assert response.context["election"].pk == election_b.pk
    assert candidate_b.name in body
    assert candidate_a.name not in body


@pytest.mark.django_db
def test_posting_without_a_chosen_election_falls_back_to_chooser(client, monkeypatch):
    """
    No `election` field in the POST body (e.g. a tampered/incomplete
    submission) while multiple elections are OPEN must land back on
    the chooser, never guess via .first() -- the exact failure mode
    Phase 1 identified.
    """
    election_a = _draft_election("Election A")
    election_b = _draft_election("Election B")
    Candidate.objects.create(election=election_a, name="Candidate A1")
    candidate_b = Candidate.objects.create(election=election_b, name="Candidate B1")
    election_a.open_voting()
    election_b.open_voting()

    _authenticate_via_real_flow(client, monkeypatch, "81000005", "+254781000005")

    response = client.post(reverse(CAST_URL_NAME), {"candidate": str(candidate_b.candidate_id)})
    body = response.content.decode()

    assert response.status_code == 200
    assert "more than one election is open" in body.lower()
    # Definitely not cast -- no Ballot exists.
    assert Ballot.objects.count() == 0


@pytest.mark.django_db
def test_full_flow_casts_ballot_for_the_chosen_election_not_the_other_one(client, monkeypatch):
    """
    End-to-end through the real view: chooser -> GET with ?election=
    -> POST the ballot form (carrying the hidden `election` field) ->
    confirmation. The resulting Ballot must belong to the CHOSEN
    election, proving the whole path -- not just cast_ballot() in
    isolation, which Phase 1 already covered -- respects the choice.
    """
    election_a = _draft_election("Election A")
    election_b = _draft_election("Election B")
    Candidate.objects.create(election=election_a, name="Candidate A1")
    candidate_b = Candidate.objects.create(election=election_b, name="Candidate B1")
    election_a.open_voting()
    election_b.open_voting()

    _authenticate_via_real_flow(client, monkeypatch, "81000006", "+254781000006")

    chooser_response = client.get(reverse(CAST_URL_NAME))
    assert election_b.title in chooser_response.content.decode()

    cast_form_response = client.get(reverse(CAST_URL_NAME), {"election": str(election_b.election_id)})
    assert candidate_b.name in cast_form_response.content.decode()

    response = client.post(
        reverse(CAST_URL_NAME),
        {"election": str(election_b.election_id), "candidate": str(candidate_b.candidate_id)},
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "recorded" in body.lower()

    ballot = Ballot.objects.get()
    assert ballot.election_id == election_b.election_id
    assert ballot.candidate_id == candidate_b.candidate_id


@pytest.mark.django_db
def test_closed_stale_choice_falls_back_to_chooser_when_others_still_open(client, monkeypatch):
    """
    The race Phase 1 flagged as a real possibility: a voter picks
    Election A while A, B, and C are all OPEN, but A gets closed (by
    an official) before the voter submits -- B and C are still both
    OPEN, so the >1-open branch applies again. The stale `election`
    value in the hidden field must not be trusted -- POST re-validates
    against the CURRENTLY open elections (fresh query, not cached from
    the GET), finds A is no longer among them, and falls back to the
    chooser (now offering only B and C) rather than casting against a
    closed election, crashing, or silently defaulting to whichever
    remains.
    """
    election_a = _draft_election("Election A")
    election_b = _draft_election("Election B")
    election_c = _draft_election("Election C")
    candidate_a = Candidate.objects.create(election=election_a, name="Candidate A1")
    Candidate.objects.create(election=election_b, name="Candidate B1")
    Candidate.objects.create(election=election_c, name="Candidate C1")
    election_a.open_voting()
    election_b.open_voting()
    election_c.open_voting()

    _authenticate_via_real_flow(client, monkeypatch, "81000007", "+254781000007")

    # Voter loaded the ballot form for Election A while all three were open.
    cast_form_response = client.get(reverse(CAST_URL_NAME), {"election": str(election_a.election_id)})
    assert candidate_a.name in cast_form_response.content.decode()

    # An official closes Election A in the meantime; B and C stay open.
    election_a.close_voting()

    response = client.post(
        reverse(CAST_URL_NAME),
        {"election": str(election_a.election_id), "candidate": str(candidate_a.candidate_id)},
    )
    body = response.content.decode()

    assert response.status_code == 200
    assert "more than one election is open" in body.lower()
    assert election_b.title in body
    assert election_c.title in body
    assert election_a.title not in body  # no longer open, not offered
    assert Ballot.objects.count() == 0