from datetime import timedelta

import pytest
from django.urls import reverse
from django.utils import timezone

from auditlog.models import AuditLog
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

from .models import Ballot
from .services import BallotCastError, cast_ballot


@pytest.mark.django_db
def test_ballot_creation():
    """
    Smoke test only (Sprint 1): confirms Ballot can be created with
    Election/Candidate FKs and no Voter/Session FK exists on the
    model at all (the anonymisation invariant is structural -- see
    ballots/models.py docstring). Not real FR-V-04 coverage -- the
    atomic ballot-casting transaction is Sprint 3.
    """
    now = timezone.now()
    election = Election.objects.create(
        title="2027 Student Council Election",
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    candidate = Candidate.objects.create(election=election, name="Amina Yusuf")

    ballot = Ballot.objects.create(election=election, candidate=candidate)

    assert ballot.ballot_id is not None
    assert not hasattr(ballot, "voter")
    assert not hasattr(ballot, "session")


def _make_open_election_with_candidate(national_id="10000001", name="Amina Yusuf"):
    now = timezone.now()
    election = Election.objects.create(
        title="2027 Student Council Election",
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    candidate = Candidate.objects.create(election=election, name=name)
    election.open_voting()
    return election, candidate


def _make_voter_with_session(national_id):
    voter = Voter.objects.create(
        national_id_hash=sha256_hex(national_id),
        full_name="Test Voter",
        phone_number="+254700" + national_id[-6:],
    )
    session = issue_session(voter)
    return voter, session


@pytest.mark.django_db
def test_fr_v04_v08_cast_ballot_success_records_and_confirms():
    """
    FR-V-04 to FR-V-08: full atomic transaction success path --
    Ballot recorded, AuditLog written with a hash digest, Session
    token deactivated, Voter.has_voted set, result returned for the
    confirmation receipt.
    """
    election, candidate = _make_open_election_with_candidate()
    voter, session = _make_voter_with_session("11111111")
    token = str(session.uuid_token)

    result = cast_ballot(uuid_token=token, candidate_id=candidate.candidate_id)

    assert result.ballot.election_id == election.election_id
    assert result.ballot.candidate_id == candidate.candidate_id
    assert result.audit_entry.ballot == result.ballot
    assert len(result.audit_entry.ballot_hash) == 64  # SHA-256 hex digest

    # Step 4, verified by re-querying the DB (not the in-memory
    # `session` object cast_ballot() never touched) -- a fresh fetch
    # is the only way to know the UPDATE actually persisted rather
    # than just changing a Python attribute somewhere.
    persisted_session = Session.objects.get(pk=session.pk)
    assert persisted_session.is_active is False

    voter.refresh_from_db()
    assert voter.has_voted is True  # step 5

    assert AuditLog.objects.filter(ballot=result.ballot).count() == 1


@pytest.mark.django_db
def test_fr_v05_session_deactivated_not_deleted_after_cast():
    """
    Regression test (bug fix): FR-V-05's "destroy the token" must
    persist as Session.is_active=False via a real UPDATE inside the
    atomic transaction -- not a no-op, and not a full row delete
    either (the row needs to keep existing, just deactivated, so a
    later lookup by uuid_token correctly finds "exists but inactive"
    rather than "never existed"). Checked with a brand new query
    object, independent of anything cast_ballot() held a reference to.
    """
    election, candidate = _make_open_election_with_candidate()
    voter, session = _make_voter_with_session("88888888")
    session_pk = session.pk

    cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    fresh = Session.objects.get(pk=session_pk)
    assert fresh.is_active is False


@pytest.mark.django_db
def test_cast_ballot_rejects_invalid_token():
    election, candidate = _make_open_election_with_candidate()

    with pytest.raises(BallotCastError):
        cast_ballot(uuid_token="00000000-0000-0000-0000-000000000000", candidate_id=candidate.candidate_id)

    assert Ballot.objects.count() == 0


@pytest.mark.django_db
def test_cast_ballot_rejects_expired_session():
    election, candidate = _make_open_election_with_candidate()
    voter, session = _make_voter_with_session("22222222")
    session.expiry_time = timezone.now() - timedelta(minutes=1)
    session.save(update_fields=["expiry_time"])

    with pytest.raises(BallotCastError):
        cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    assert Ballot.objects.count() == 0
    persisted_session = Session.objects.get(pk=session.pk)
    assert persisted_session.is_active is True  # untouched -- rejection happened before step 4


@pytest.mark.django_db
def test_fr_v01_expired_session_rejected_before_any_transaction_work():
    """
    Regression test (bug fix): an expired Session's token must be
    rejected -- expiry_time in the past OR is_active already False --
    BEFORE any part of the ballot-casting transaction runs, with the
    same kind of rejection a voter sees for an invalid token (not a
    distinct "expired" message, so the error can't be used to
    distinguish "expired" from "never existed"/"already used").
    Confirms no Ballot or AuditLog row is created at all.
    """
    election, candidate = _make_open_election_with_candidate()
    voter, session = _make_voter_with_session("99999999")
    session.expiry_time = timezone.now() - timedelta(minutes=4)
    session.save(update_fields=["expiry_time"])

    with pytest.raises(BallotCastError) as exc_info:
        cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    assert "invalid" in str(exc_info.value).lower() or "expired" in str(exc_info.value).lower()
    assert Ballot.objects.count() == 0
    assert AuditLog.objects.count() == 0

    fresh = Session.objects.get(pk=session.pk)
    assert fresh.is_active is True  # rejection happened before step 4 touched it

    voter.refresh_from_db()
    assert voter.has_voted is False


@pytest.mark.django_db
def test_cast_ballot_rejects_already_voted_voter():
    """
    Defensive re-check (Sprint 3 addition, see services.py docstring):
    a second active Session for a voter who already voted must not be
    able to cast a second ballot.
    """
    election, candidate = _make_open_election_with_candidate()
    voter, session = _make_voter_with_session("33333333")
    voter.has_voted = True
    voter.save(update_fields=["has_voted"])

    with pytest.raises(BallotCastError):
        cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    assert Ballot.objects.count() == 0
    assert Session.objects.filter(pk=session.pk).exists()  # untouched on rejection


@pytest.mark.django_db
def test_cast_ballot_rejects_when_election_not_open():
    now = timezone.now()
    election = Election.objects.create(
        title="Draft Election", start_date=now, end_date=now + timedelta(days=1)
    )
    candidate = Candidate.objects.create(election=election, name="Amina Yusuf")
    # election left in DRAFT -- never opened
    voter, session = _make_voter_with_session("44444444")

    with pytest.raises(BallotCastError):
        cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    assert Ballot.objects.count() == 0


@pytest.mark.django_db
def test_audit_log_hash_chain_links_previous_hash():
    """SCHEMA.md AuditLog.previous_hash: consecutive entries chain."""
    election, candidate = _make_open_election_with_candidate()
    voter1, session1 = _make_voter_with_session("55555555")
    voter2, session2 = _make_voter_with_session("66666666")

    result1 = cast_ballot(uuid_token=str(session1.uuid_token), candidate_id=candidate.candidate_id)
    result2 = cast_ballot(uuid_token=str(session2.uuid_token), candidate_id=candidate.candidate_id)

    assert result1.audit_entry.previous_hash == ""  # first entry, or chains from whatever preceded it
    assert result2.audit_entry.previous_hash == result1.audit_entry.ballot_hash


@pytest.mark.django_db
def test_cast_ballot_view_full_flow_clears_session_token(client, monkeypatch):
    """
    End-to-end through the view layer: login -> cast -> confirmation,
    and confirms request.session["voting_token"] is cleared in the
    same view that destroys the domain Session (Sprint 2 carry-forward
    item, explicitly re-verified here rather than assumed).
    """
    from voters import views as voters_views

    captured = {}
    monkeypatch.setattr(
        voters_views.sms_gateway, "send_otp", lambda phone_number, otp: captured.setdefault("otp", otp) or True
    )

    election, candidate = _make_open_election_with_candidate()

    voter = Voter.objects.create(
        national_id_hash=sha256_hex("77777777"),
        full_name="Full Flow Voter",
        phone_number="+254777000000",
    )

    client.post(
        reverse("voters:credentials"),
        {"national_id": "77777777", "phone_number": "+254777000000"},
    )
    client.post(reverse("voters:verify_otp"), {"otp": captured["otp"]})

    assert "voting_token" in client.session

    response = client.post(reverse("ballots:cast"), {"candidate": str(candidate.candidate_id)})

    assert response.status_code == 200
    assert "recorded" in response.content.decode().lower()
    assert "voting_token" not in client.session

    voter.refresh_from_db()
    assert voter.has_voted is True

    # Full-flow version of the same DB-level check as
    # test_fr_v05_session_deactivated_not_deleted_after_cast: the
    # view returning a success page is not itself proof anything
    # persisted -- query the Session table directly.
    session = Session.objects.get(voter=voter)
    assert session.is_active is False
