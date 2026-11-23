"""
FR-EL-07 (EXTENSIONS_ROADMAP.md): multi-ballot voting flow ("cycle-lite").

Extension ID, not a core requirement. The "cycle" is simply the set of
elections that are OPEN right now: no ElectionCycle model, no schema
change. Every test name carries the ID. Existing ballots/test_fr_el_06_*
tests are untouched and still pass.
"""

from datetime import timedelta

import pytest
from django.apps import apps
from django.core.management import call_command
from django.db import connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from auditlog.models import AuditLog
from ballots.models import Ballot
from ballots.services import BallotCastError, cast_ballot
from elections.models import Candidate, Election
from voter_sessions import hygiene
from voter_sessions.models import Session
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY
from voters import views as voter_views
from voters.crypto_utils import sha256_hex
from voters.models import Voter, VoterElectionParticipation

CAST = "ballots:cast"
NATIONAL_ID = "77777701"
PHONE = "+254700007701"


def _election(title, hours_ago=0):
    start = timezone.now() - timedelta(hours=hours_ago)
    election = Election.objects.create(title=title, start_date=start, end_date=start + timedelta(days=1))
    cands = [
        Candidate.objects.create(election=election, name=f"{title} Candidate One"),
        Candidate.objects.create(election=election, name=f"{title} Candidate Two"),
    ]
    election.open_voting()
    return election, cands


@pytest.fixture(autouse=True)
def fixed_otp(monkeypatch):
    monkeypatch.setattr(voter_views, "_generate_otp", lambda: "123456")


@pytest.fixture
def voter():
    return Voter.objects.create(national_id_hash=sha256_hex(NATIONAL_ID), full_name="Cyc Le Voter", phone_number=PHONE)


@pytest.fixture
def cycle(voter):
    """President (earlier start) and Governor (later start), both OPEN."""
    president, pc = _election("President 2026", hours_ago=2)
    governor, gc = _election("Governor 2026", hours_ago=1)
    return {"president": president, "pc": pc, "governor": governor, "gc": gc}


def _login(client=None):
    client = client or Client()
    assert client.post("/voters/login/", {"national_id": NATIONAL_ID, "phone_number": PHONE}).status_code == 302
    assert client.post("/voters/verify-otp/", {"otp": "123456"}).status_code == 200
    return client


def _vote(client, election, candidate):
    return client.post(reverse(CAST), {"election": str(election.election_id), "candidate": str(candidate.candidate_id)})


def _statuses(body):
    """[(title, 'done'|'pending')] in page order, from the checklist."""
    out = []
    block = body.split('data-testid="ballot-checklist"', 1)[1].split("</ul>", 1)[0]
    for chunk in block.split("<li")[1:]:
        status = "done" if 'data-status="done"' in chunk else "pending"
        title = chunk.split("font-semibold", 1)[1].split(">", 1)[1].split("<", 1)[0].strip()
        out.append((title, status))
    return out


# ---------------------------------------------------------------------
# Checklist
# ---------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_el07_checklist_lists_open_elections_in_start_date_then_title_order(voter, cycle):
    client = _login()
    body = client.get(reverse(CAST)).content.decode()

    assert _statuses(body) == [("President 2026", "pending"), ("Governor 2026", "pending")]


@pytest.mark.django_db
def test_fr_el07_ordering_falls_back_to_title_when_start_dates_match(voter):
    start = timezone.now()
    for title in ("Zeta Race", "Alpha Race"):
        e = Election.objects.create(title=title, start_date=start, end_date=start + timedelta(days=1))
        Candidate.objects.create(election=e, name=f"{title} C")
        e.open_voting()
    body = _login().get(reverse(CAST)).content.decode()

    assert [t for t, _ in _statuses(body)] == ["Alpha Race", "Zeta Race"]


@pytest.mark.django_db
def test_fr_el07_checklist_shows_done_and_pending_correctly(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])

    body = client.get(reverse(CAST)).content.decode()

    assert _statuses(body) == [("President 2026", "done"), ("Governor 2026", "pending")]
    # Done ones are not links; pending ones are.
    assert f"?election={cycle['governor'].election_id}" in body
    assert f"?election={cycle['president'].election_id}" not in body


@pytest.mark.django_db
def test_fr_el07_only_pending_elections_can_be_opened_as_a_ballot_form(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])

    body = client.get(f"{reverse(CAST)}?election={cycle['president'].election_id}").content.decode()

    assert "President 2026 Candidate One" not in body  # no ballot form for a finished election
    assert 'data-testid="ballot-checklist"' in body


# ---------------------------------------------------------------------
# Continuation: new token, no OTP, previous token dead
# ---------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_el07_continuation_issues_a_new_token_without_otp_and_old_token_is_dead(voter, cycle, monkeypatch):
    client = _login()
    first_token = client.session[VOTING_TOKEN_SESSION_KEY]
    # No OTP may be requested from here on.
    monkeypatch.setattr(voter_views.sms_gateway, "send_otp", lambda *a, **k: pytest.fail("OTP requested"))

    response = _vote(client, cycle["president"], cycle["pc"][0])
    body = response.content.decode()

    assert 'data-testid="continue-panel"' in body
    assert "Continue to next ballot" in body
    assert "Governor 2026" in body
    second_token = client.session[VOTING_TOKEN_SESSION_KEY]
    assert second_token != first_token
    assert Session.objects.get(uuid_token=first_token).is_active is False
    assert Session.objects.get(uuid_token=second_token).is_active is True
    with pytest.raises(BallotCastError):
        cast_ballot(uuid_token=first_token, candidate_id=cycle["gc"][0].candidate_id)


@pytest.mark.django_db
def test_fr_el07_full_cycle_each_ballot_has_its_own_single_use_token(voter, cycle):
    client = _login()
    tokens = [client.session[VOTING_TOKEN_SESSION_KEY]]
    _vote(client, cycle["president"], cycle["pc"][0])
    tokens.append(client.session[VOTING_TOKEN_SESSION_KEY])
    _vote(client, cycle["governor"], cycle["gc"][1])

    assert Ballot.objects.count() == 2
    assert len(set(tokens)) == 2
    assert Session.objects.filter(voter=voter, is_active=True).count() == 0
    assert AuditLog.objects.count() == 2
    assert VoterElectionParticipation.objects.filter(voter=voter, has_voted=True).count() == 2


@pytest.mark.django_db
def test_fr_el07_continuation_keeps_the_original_login_time(voter, cycle):
    client = _login()
    original = client.session[hygiene.AUTHENTICATED_AT_SESSION_KEY]

    _vote(client, cycle["president"], cycle["pc"][0])

    assert client.session[hygiene.AUTHENTICATED_AT_SESSION_KEY] == original


# ---------------------------------------------------------------------
# Skip
# ---------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_el07_skip_moves_on_and_records_nothing(voter, cycle):
    client = _login()
    token = client.session[VOTING_TOKEN_SESSION_KEY]
    page = client.get(f"{reverse(CAST)}?election={cycle['president'].election_id}").content.decode()
    assert 'data-testid="skip-link"' in page
    skip_href = page.split('data-testid="skip-link" href="', 1)[1].split('"', 1)[0]
    assert skip_href.endswith(str(cycle["governor"].election_id))
    before = (Ballot.objects.count(), AuditLog.objects.count(), VoterElectionParticipation.objects.count())

    nxt = client.get(skip_href).content.decode()

    assert "Governor 2026 Candidate One" in nxt
    assert (Ballot.objects.count(), AuditLog.objects.count(), VoterElectionParticipation.objects.count()) == before
    assert client.session[VOTING_TOKEN_SESSION_KEY] == token
    assert Session.objects.get(uuid_token=token).is_active is True


@pytest.mark.django_db
def test_fr_el07_skip_link_absent_when_no_other_ballot_is_pending(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])

    page = client.get(f"{reverse(CAST)}?election={cycle['governor'].election_id}").content.decode()

    assert 'data-testid="skip-link"' not in page


@pytest.mark.django_db
def test_fr_el07_end_session_with_ballots_pending_then_login_resumes(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])
    client.post("/voters/end-session/")

    resumed = _login(Client())
    body = resumed.get(reverse(CAST)).content.decode()

    assert _statuses(body) == [("President 2026", "done"), ("Governor 2026", "pending")]
    assert Ballot.objects.count() == 1


# ---------------------------------------------------------------------
# All done
# ---------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_el07_all_done_ends_the_session(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])
    last = _vote(client, cycle["governor"], cycle["gc"][0])
    body = last.content.decode()

    assert 'data-testid="all-done-panel"' in body
    assert "All ballots cast" in body
    assert "Continue to next ballot" not in body
    assert "recorded" in body.lower()  # the last ballot's own receipt is still shown
    assert VOTING_TOKEN_SESSION_KEY not in client.session
    assert hygiene.AUTHENTICATED_AT_SESSION_KEY not in client.session
    assert "need to log in" in client.get(reverse(CAST)).content.decode()


@pytest.mark.django_db
def test_fr_el07_single_open_election_goes_straight_to_all_done(voter):
    election, cands = _election("Only Race")
    client = _login()

    body = _vote(client, election, cands[0]).content.decode()

    assert 'data-testid="all-done-panel"' in body
    assert VOTING_TOKEN_SESSION_KEY not in client.session


# ---------------------------------------------------------------------
# One vote per election
# ---------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_el07_cannot_vote_twice_in_one_election(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])
    live_token = client.session[VOTING_TOKEN_SESSION_KEY]

    again = _vote(client, cycle["president"], cycle["pc"][1])  # same election, fresh token

    assert Ballot.objects.filter(election=cycle["president"]).count() == 1
    assert "President 2026 Candidate Two" not in again.content.decode()
    # And even bypassing the view, the service itself refuses.
    with pytest.raises(BallotCastError):
        cast_ballot(uuid_token=live_token, candidate_id=cycle["pc"][1].candidate_id)
    assert Ballot.objects.filter(election=cycle["president"]).count() == 1


# ---------------------------------------------------------------------
# Elections opening and closing mid-flow
# ---------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_el07_election_that_closes_mid_flow_drops_out(voter, cycle):
    client = _login()
    cycle["governor"].close_voting()

    body = client.get(reverse(CAST)).content.decode()

    assert "Governor 2026" not in body  # one open election left -> straight to its ballot form
    assert "President 2026" in body


@pytest.mark.django_db
def test_fr_el07_closing_the_last_pending_election_means_all_done_after_the_ballot(voter, cycle):
    client = _login()
    cycle["governor"].close_voting()

    body = _vote(client, cycle["president"], cycle["pc"][0]).content.decode()

    assert 'data-testid="all-done-panel"' in body
    assert 'data-testid="continue-panel"' not in body


@pytest.mark.django_db
def test_fr_el07_election_that_opens_mid_flow_appears(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])
    third, _ = _election("Senator 2026", hours_ago=0)

    body = client.get(reverse(CAST)).content.decode()

    assert ("Senator 2026", "pending") in _statuses(body)


# ---------------------------------------------------------------------
# Timeout blocks continuation
# ---------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_el07_absolute_timeout_blocks_continuation(voter, cycle, monkeypatch):
    client = _login()
    sessions_before = Session.objects.count()
    # First call (start of request): still inside the limit. Second call
    # (after the ballot is committed): limit passed.
    answers = iter([False, True])
    monkeypatch.setattr(hygiene, "absolute_timeout_exceeded", lambda request: next(answers))

    body = _vote(client, cycle["president"], cycle["pc"][0]).content.decode()

    assert Ballot.objects.count() == 1  # the ballot itself was committed
    assert 'data-testid="timed-out-panel"' in body
    assert "Continue to next ballot" not in body
    assert VOTING_TOKEN_SESSION_KEY not in client.session
    assert Session.objects.count() == sessions_before  # no new token minted


@pytest.mark.django_db
def test_fr_el07_timeout_before_the_ballot_still_blocks_voting(voter, cycle):
    client = _login()
    s = client.session
    s[hygiene.AUTHENTICATED_AT_SESSION_KEY] = (timezone.now() - timedelta(minutes=31)).isoformat()
    s.save()

    response = _vote(client, cycle["president"], cycle["pc"][0])

    assert "Session expired" in response.content.decode()
    assert Ballot.objects.count() == 0


# ---------------------------------------------------------------------
# Anonymity
# ---------------------------------------------------------------------

def test_fr_el07_no_new_model_field_or_relation_links_ballots():
    names = {m.__name__ for m in apps.get_models()}
    assert not {n for n in names if "cycle" in n.lower() or "paper" in n.lower()}

    ballot_fields = {f.name for f in Ballot._meta.get_fields()}
    # AuditLog's one-way ballot FK shows up here as a reverse relation.
    assert ballot_fields == {"ballot_id", "created_at", "candidate", "election", "audit_log"}

    participation = {f.name for f in VoterElectionParticipation._meta.get_fields()}
    assert participation == {"id", "voter", "election", "has_voted", "voted_at"}

    # The only model with a relation pointing at Ballot is AuditLog.
    pointing = {
        m.__name__ for m in apps.get_models()
        for f in m._meta.get_fields()
        if getattr(f, "related_model", None) is Ballot and f.concrete
    }
    assert pointing == {"AuditLog"}
    # Nothing relates Ballot to Voter or Session, in either direction.
    for model in (Voter, Session):
        assert not [f for f in Ballot._meta.get_fields() if getattr(f, "related_model", None) is model]
        assert not [f for f in model._meta.get_fields() if getattr(f, "related_model", None) is Ballot]


@pytest.mark.django_db
def test_fr_el07_no_schema_change_is_needed():
    # Fails if any model change would need a migration.
    call_command("makemigrations", check=True, dry_run=True, verbosity=0)


@pytest.mark.django_db
def test_fr_el07_a_voters_ballots_share_no_identifier(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])
    _vote(client, cycle["governor"], cycle["gc"][1])

    president_ballot = Ballot.objects.get(election=cycle["president"])
    governor_ballot = Ballot.objects.get(election=cycle["governor"])
    columns = ("ballot_id", "election_id", "candidate_id", "created_at")
    row_a = {c: getattr(president_ballot, c) for c in columns}
    row_b = {c: getattr(governor_ballot, c) for c in columns}
    assert all(row_a[c] != row_b[c] for c in columns)  # nothing in common
    assert set(row_a) == set(columns)  # and there is no other column to share


@pytest.mark.django_db
def test_fr_el07_checklist_is_built_from_participation_rows_only(voter, cycle):
    client = _login()
    _vote(client, cycle["president"], cycle["pc"][0])

    with CaptureQueriesContext(connection) as queries:
        assert client.get(reverse(CAST)).status_code == 200

    sql = " ".join(q["sql"].lower() for q in queries.captured_queries)
    assert "voters_voterelectionparticipation" in sql
    for forbidden in ("ballots_ballot", "elections_candidate", "auditlog_auditlog"):
        assert forbidden not in sql


@pytest.mark.django_db
def test_fr_el07_checklist_leaks_no_choice_or_identity(voter, cycle):
    client = _login()
    token = client.session[VOTING_TOKEN_SESSION_KEY]
    _vote(client, cycle["president"], cycle["pc"][0])
    ballot = Ballot.objects.get()
    audit = AuditLog.objects.get()

    response = client.get(reverse(CAST))
    body = response.content.decode()

    for secret in (
        "President 2026 Candidate One", "President 2026 Candidate Two",
        "Governor 2026 Candidate One", "Governor 2026 Candidate Two",
        str(ballot.ballot_id), audit.ballot_hash, str(voter.voter_id), voter.full_name,
        voter.phone_number, voter.national_id_hash, token, client.session[VOTING_TOKEN_SESSION_KEY],
    ):
        assert secret not in body
    context = response.context
    values = [context.get(k) for k in context.keys()] if hasattr(context, "keys") else list(context.flatten().values())
    for value in values:
        assert not isinstance(value, (Voter, Session, Ballot, AuditLog, Candidate, VoterElectionParticipation))
    for entry in context["entries"]:
        assert set(entry) == {"election", "done"}
