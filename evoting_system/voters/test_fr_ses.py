"""
FR-SES-01 to FR-SES-03 (EXTENSIONS_ROADMAP.md): session hygiene.

Extension IDs, not core requirements. FR-SES-01 deactivates a voter's
earlier sessions at OTP success; FR-SES-02 is an absolute timeout since
OTP success; FR-SES-03 is the voter's explicit "End session".
"""

from datetime import timedelta

import pytest
from django.test import Client
from django.utils import timezone

from ballots.models import Ballot
from ballots.services import BallotCastError, cast_ballot
from elections.models import Candidate, Election
from voter_sessions import hygiene
from voter_sessions.models import Session
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session
from voters import views as voter_views
from voters.crypto_utils import sha256_hex
from voters.models import Voter

NATIONAL_ID = "55555501"
PHONE = "+254700005501"


@pytest.fixture
def open_election():
    election = Election.objects.create(
        title="Hygiene Election", start_date=timezone.now(), end_date=timezone.now() + timedelta(hours=2)
    )
    candidate = Candidate.objects.create(election=election, name="Hygiene Candidate")
    election.open_voting()
    return election, candidate


@pytest.fixture
def voter(open_election):
    return Voter.objects.create(national_id_hash=sha256_hex(NATIONAL_ID), full_name="Hy Giene", phone_number=PHONE)


@pytest.fixture(autouse=True)
def fixed_otp(monkeypatch):
    monkeypatch.setattr(voter_views, "_generate_otp", lambda: "123456")


def _login(client, national_id=NATIONAL_ID, phone=PHONE):
    """Full credentials -> OTP flow through the real views."""
    r = client.post("/voters/login/", {"national_id": national_id, "phone_number": phone})
    assert r.status_code == 302, "credentials step should redirect to OTP"
    r = client.post("/voters/verify-otp/", {"otp": "123456"})
    assert r.status_code == 200
    return client.session[VOTING_TOKEN_SESSION_KEY]


def _set_authenticated_at(client, delta):
    s = client.session
    s[hygiene.AUTHENTICATED_AT_SESSION_KEY] = (timezone.now() - delta).isoformat()
    s.save()


# ----------------------------------------------------------------------
# FR-SES-01
# ----------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_ses01_second_login_deactivates_first_session(voter):
    first_client, second_client = Client(), Client()

    first_token = _login(first_client)
    assert Session.objects.get(uuid_token=first_token).is_active is True

    second_token = _login(second_client)

    assert Session.objects.get(uuid_token=first_token).is_active is False
    assert Session.objects.get(uuid_token=second_token).is_active is True
    assert Session.objects.filter(voter=voter, is_active=True).count() == 1


@pytest.mark.django_db
def test_fr_ses01_old_token_is_rejected_after_second_login(voter, open_election):
    _, candidate = open_election
    first_client, second_client = Client(), Client()
    first_token = _login(first_client)
    _login(second_client)

    with pytest.raises(BallotCastError):
        cast_ballot(uuid_token=first_token, candidate_id=candidate.candidate_id)
    assert Ballot.objects.count() == 0


@pytest.mark.django_db
def test_fr_ses01_only_this_voters_sessions_are_deactivated(voter):
    other = Voter.objects.create(national_id_hash=sha256_hex("55555502"), full_name="Other V", phone_number="+254700005502")
    other_session = issue_session(other)

    _login(Client())

    other_session.refresh_from_db()
    assert other_session.is_active is True


@pytest.mark.django_db
def test_fr_ses01_issue_session_itself_still_allows_two_active_sessions(voter):
    """Guard: the rule lives in the view layer; issue_session is unchanged
    (voters/test_fr_el_05.py relies on creating two active sessions)."""
    issue_session(voter)
    issue_session(voter)

    assert Session.objects.filter(voter=voter, is_active=True).count() == 2


@pytest.mark.django_db
def test_fr_ses01_failed_otp_does_not_deactivate_existing_session(voter):
    first_token = _login(Client())
    attacker = Client()
    attacker.post("/voters/login/", {"national_id": NATIONAL_ID, "phone_number": PHONE})
    attacker.post("/voters/verify-otp/", {"otp": "000000"})

    assert Session.objects.get(uuid_token=first_token).is_active is True


# ----------------------------------------------------------------------
# FR-SES-02
# ----------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_ses02_otp_success_records_authenticated_at(voter):
    client = Client()
    before = timezone.now()
    _login(client)

    recorded = client.session[hygiene.AUTHENTICATED_AT_SESSION_KEY]
    assert before <= timezone.datetime.fromisoformat(recorded) <= timezone.now()


@pytest.mark.django_db
def test_fr_ses02_within_limit_the_ballot_page_works(voter):
    client = Client()
    _login(client)
    _set_authenticated_at(client, timedelta(minutes=5))

    response = client.get("/ballots/cast/")

    assert response.status_code == 200
    assert "Session expired" not in response.content.decode()
    assert "Hygiene Candidate" in response.content.decode()


@pytest.mark.django_db
def test_fr_ses02_past_limit_session_expires_and_token_is_deactivated(voter):
    client = Client()
    token = _login(client)
    _set_authenticated_at(client, timedelta(minutes=31))

    response = client.get("/ballots/cast/")
    body = response.content.decode()

    assert "Session expired" in body
    assert 'href="/voters/login/"' in body
    assert Session.objects.get(uuid_token=token).is_active is False
    assert VOTING_TOKEN_SESSION_KEY not in client.session
    assert hygiene.AUTHENTICATED_AT_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_fr_ses02_past_limit_a_post_cannot_cast_a_ballot(voter, open_election):
    _, candidate = open_election
    client = Client()
    _login(client)
    _set_authenticated_at(client, timedelta(minutes=31))

    response = client.post("/ballots/cast/", {"candidate": str(candidate.candidate_id)})

    assert "Session expired" in response.content.decode()
    assert Ballot.objects.count() == 0


@pytest.mark.django_db
def test_fr_ses02_limit_is_a_setting(voter, settings):
    settings.VOTER_SESSION_ABSOLUTE_TIMEOUT_MINUTES = 1
    client = Client()
    _login(client)
    _set_authenticated_at(client, timedelta(minutes=2))

    assert "Session expired" in client.get("/ballots/cast/").content.decode()


@pytest.mark.django_db
def test_fr_ses02_default_limit_is_30_minutes():
    assert hygiene.DEFAULT_ABSOLUTE_TIMEOUT_MINUTES == 30
    assert hygiene.absolute_timeout() == timedelta(minutes=30)


@pytest.mark.django_db
def test_fr_ses02_session_without_timestamp_is_not_expired_by_this_rule(voter):
    """A browser session with a token but no authenticated_at (pre-feature
    sessions, tests that set the token directly) is left to the token's own
    15-minute expiry inside cast_ballot."""
    client = Client()
    session = issue_session(voter)
    s = client.session
    s[VOTING_TOKEN_SESSION_KEY] = str(session.uuid_token)
    s.save()

    assert "Session expired" not in client.get("/ballots/cast/").content.decode()


@pytest.mark.django_db
def test_fr_ses02_unreadable_timestamp_fails_closed(voter):
    client = Client()
    token = _login(client)
    s = client.session
    s[hygiene.AUTHENTICATED_AT_SESSION_KEY] = "not-a-timestamp"
    s.save()

    assert "Session expired" in client.get("/ballots/cast/").content.decode()
    assert Session.objects.get(uuid_token=token).is_active is False


# ----------------------------------------------------------------------
# FR-SES-03
# ----------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_ses03_end_session_deactivates_token_and_clears_keys(voter):
    client = Client()
    token = _login(client)

    response = client.post("/voters/end-session/")

    assert response.status_code == 200
    assert "Session ended" in response.content.decode()
    assert Session.objects.get(uuid_token=token).is_active is False
    assert Session.objects.filter(uuid_token=token).exists()  # deactivated, not deleted
    assert VOTING_TOKEN_SESSION_KEY not in client.session
    assert hygiene.AUTHENTICATED_AT_SESSION_KEY not in client.session


@pytest.mark.django_db
def test_fr_ses03_old_token_is_rejected_after_end_session(voter, open_election):
    _, candidate = open_election
    client = Client()
    token = _login(client)
    client.post("/voters/end-session/")

    # The browser can no longer reach the ballot form...
    assert "need to log in" in client.get("/ballots/cast/").content.decode()
    # ...and the old token itself is dead server-side.
    with pytest.raises(BallotCastError):
        cast_ballot(uuid_token=token, candidate_id=candidate.candidate_id)
    assert Ballot.objects.count() == 0


@pytest.mark.django_db
def test_fr_ses03_end_session_clears_a_half_finished_otp_step(voter):
    client = Client()
    client.post("/voters/login/", {"national_id": NATIONAL_ID, "phone_number": PHONE})
    assert "pending_auth_voter_id" in client.session

    client.post("/voters/end-session/")

    assert "pending_auth_voter_id" not in client.session
    assert "pending_auth_expiry" not in client.session


@pytest.mark.django_db
def test_fr_ses03_end_session_without_a_session_is_harmless(client):
    response = client.post("/voters/end-session/")

    assert response.status_code == 200
    assert "Session ended" in response.content.decode()


@pytest.mark.django_db
def test_fr_ses03_end_session_is_post_only_and_needs_csrf(voter):
    assert Client().get("/voters/end-session/").status_code == 405

    strict = Client(enforce_csrf_checks=True)
    assert strict.post("/voters/end-session/").status_code == 403


@pytest.mark.django_db
def test_fr_ses03_end_session_only_affects_the_current_token(voter):
    other = Voter.objects.create(national_id_hash=sha256_hex("55555503"), full_name="Oth Er", phone_number="+254700005503")
    other_session = issue_session(other)
    client = Client()
    _login(client)

    client.post("/voters/end-session/")

    other_session.refresh_from_db()
    assert other_session.is_active is True


@pytest.mark.django_db
def test_fr_ses03_end_session_touches_no_ballot_or_audit_data(voter, open_election):
    from auditlog.models import AuditLog

    client = Client()
    _login(client)
    before = (Ballot.objects.count(), AuditLog.objects.count())

    client.post("/voters/end-session/")

    assert (Ballot.objects.count(), AuditLog.objects.count()) == before


@pytest.mark.django_db
def test_fr_ses03_normal_voting_still_works_end_to_end(voter, open_election):
    """Regression guard for the whole feature set: login -> ballot -> confirmation."""
    _, candidate = open_election
    client = Client()
    _login(client)

    response = client.post("/ballots/cast/", {"candidate": str(candidate.candidate_id)})

    assert response.status_code == 200
    assert Ballot.objects.count() == 1
    assert VOTING_TOKEN_SESSION_KEY not in client.session
