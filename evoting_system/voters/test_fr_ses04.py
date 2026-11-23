"""
FR-SES-04 (EXTENSIONS_ROADMAP.md): wrong-OTP attempt limit.

Hardening of FR-V-03 after security-run finding F2. After
OTP_MAX_FAILED_ATTEMPTS (5) consecutive wrong OTPs on one pending login
the OTP hash is cleared (the pending login is dead for every browser),
one AuthSecurityEvent('otp_lockout') row is written with no
identifying data, and the voter must log in again with credentials.
The counter is Voter.otp_failed_attempts, reset whenever a new OTP is
issued, and counted under a row lock (select_for_update).
"""

import threading
import time
from datetime import timedelta

import pytest
from django.db import connection
from django.test import Client
from django.utils import timezone

from auditlog.models import AuthSecurityEvent
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY
from voters import views as voter_views
from voters.crypto_utils import sha256_hex
from voters.models import Voter

NATIONAL_ID = "55555504"
PHONE = "+254700005504"
OTP = "123456"
WRONG = "000000"
LIMIT = voter_views.OTP_MAX_FAILED_ATTEMPTS


@pytest.fixture
def voter():
    election = Election.objects.create(
        title="Lockout Election", start_date=timezone.now(), end_date=timezone.now() + timedelta(hours=2)
    )
    Candidate.objects.create(election=election, name="Lockout Candidate")
    election.open_voting()
    return Voter.objects.create(national_id_hash=sha256_hex(NATIONAL_ID), full_name="Lock Out", phone_number=PHONE)


@pytest.fixture(autouse=True)
def fixed_otp(monkeypatch):
    monkeypatch.setattr(voter_views, "_generate_otp", lambda: OTP)


def _start(client):
    r = client.post("/voters/login/", {"national_id": NATIONAL_ID, "phone_number": PHONE})
    assert r.status_code == 302


def _otp(client, code):
    return client.post("/voters/verify-otp/", {"otp": code})


def test_fr_ses04_limit_is_five():
    assert LIMIT == 5


@pytest.mark.django_db
def test_fr_ses04_counter_increments_once_per_wrong_attempt(voter):
    client = Client()
    _start(client)
    for n in range(1, LIMIT):
        r = _otp(client, WRONG)
        assert r.status_code == 200
        assert b"Incorrect OTP." in r.content
        voter.refresh_from_db()
        assert voter.otp_failed_attempts == n
    assert AuthSecurityEvent.objects.count() == 0


@pytest.mark.django_db
def test_fr_ses04_correct_otp_before_limit_works_and_resets_count(voter):
    client = Client()
    _start(client)
    for _ in range(LIMIT - 1):
        _otp(client, WRONG)
    r = _otp(client, OTP)
    assert r.status_code == 200
    assert VOTING_TOKEN_SESSION_KEY in client.session
    voter.refresh_from_db()
    assert voter.otp_failed_attempts == 0
    assert AuthSecurityEvent.objects.count() == 0


@pytest.mark.django_db
def test_fr_ses04_lockout_at_limit_writes_exactly_one_event(voter):
    client = Client()
    _start(client)
    for _ in range(LIMIT - 1):
        _otp(client, WRONG)
    r = _otp(client, WRONG)

    assert r.status_code == 200
    assert b"Too many incorrect codes" in r.content
    voter.refresh_from_db()
    assert voter.otp_failed_attempts == LIMIT
    assert voter.otp_hash == ""
    assert voter_views.PENDING_VOTER_SESSION_KEY not in client.session
    assert voter_views.PENDING_EXPIRY_SESSION_KEY not in client.session
    assert AuthSecurityEvent.objects.count() == 1
    assert AuthSecurityEvent.objects.get().event_type == "otp_lockout"

    # Further attempts on the same browser need a fresh credentials login
    # and write no further event.
    r = _otp(client, OTP)
    assert r.status_code == 302 and r.url.endswith("/voters/login/")
    assert AuthSecurityEvent.objects.count() == 1


@pytest.mark.django_db
def test_fr_ses04_event_row_holds_no_identifying_data(voter):
    fields = {f.name for f in AuthSecurityEvent._meta.get_fields()}
    assert fields == {"id", "timestamp", "event_type"}
    assert not [f for f in AuthSecurityEvent._meta.get_fields() if f.is_relation]

    client = Client()
    _start(client)
    for _ in range(LIMIT):
        _otp(client, WRONG)

    row = AuthSecurityEvent.objects.values().get()
    assert set(row) == {"id", "timestamp", "event_type"}
    text = " ".join(str(v) for v in row.values())
    for secret in (NATIONAL_ID, sha256_hex(NATIONAL_ID), PHONE, OTP, WRONG, sha256_hex(OTP),
                   str(voter.voter_id), voter.full_name):
        assert secret not in text


@pytest.mark.django_db
def test_fr_ses04_correct_otp_after_lockout_refused_from_any_browser(voter):
    attacker = Client()
    _start(attacker)

    # A second browser holding the same pending login (its own Django
    # session with the pending keys), as if prepared before the lockout.
    other = Client()
    other_session = other.session
    other_session[voter_views.PENDING_VOTER_SESSION_KEY] = str(voter.voter_id)
    other_session[voter_views.PENDING_EXPIRY_SESSION_KEY] = (timezone.now() + timedelta(minutes=5)).isoformat()
    other_session.save()
    other.cookies["sessionid"] = other_session.session_key

    for _ in range(LIMIT):
        _otp(attacker, WRONG)

    r = _otp(other, OTP)
    assert r.status_code == 200
    assert b"no longer valid" in r.content
    assert VOTING_TOKEN_SESSION_KEY not in other.session
    assert not Session.objects.filter(voter=voter).exists()
    # The dead login is not counted again and writes no second event.
    voter.refresh_from_db()
    assert voter.otp_failed_attempts == LIMIT
    assert AuthSecurityEvent.objects.count() == 1


@pytest.mark.django_db
def test_fr_ses04_new_login_issues_new_otp_and_counter_starts_at_zero(voter, monkeypatch):
    client = Client()
    _start(client)
    for _ in range(LIMIT):
        _otp(client, WRONG)
    voter.refresh_from_db()
    assert voter.otp_failed_attempts == LIMIT and voter.otp_hash == ""

    monkeypatch.setattr(voter_views, "_generate_otp", lambda: "654321")
    _start(client)
    voter.refresh_from_db()
    assert voter.otp_hash == sha256_hex("654321")
    assert voter.otp_failed_attempts == 0

    # The counter did not carry over: a wrong attempt counts as the first.
    _otp(client, WRONG)
    voter.refresh_from_db()
    assert voter.otp_failed_attempts == 1
    r = _otp(client, "654321")
    assert VOTING_TOKEN_SESSION_KEY in client.session
    assert AuthSecurityEvent.objects.count() == 1


@pytest.mark.django_db(transaction=True)
def test_fr_ses04_parallel_wrong_attempts_never_exceed_limit(voter, monkeypatch):
    """
    Fires parallel wrong OTPs at one pending login from many threads
    (each with its own DB connection, all sharing one browser-session
    cookie, started together by a barrier). The row lock must keep the
    count at exactly the limit and write exactly one lockout event.

    Voter.save is slowed by 50 ms when it writes the counter, to widen
    the read-then-write window. With select_for_update the other
    threads wait on the row lock and see the updated count; without it
    (checked by temporarily removing the lock) they all read the same
    stale count and this test fails.
    """
    first = Client()
    _start(first)
    cookie = first.cookies["sessionid"].value

    real_save = Voter.save

    def slow_save(self, *args, **kwargs):
        if "otp_failed_attempts" in (kwargs.get("update_fields") or ()):
            time.sleep(0.05)
        return real_save(self, *args, **kwargs)

    monkeypatch.setattr(Voter, "save", slow_save)

    threads_n = 12
    barrier = threading.Barrier(threads_n)
    statuses, errors = [], []

    def attempt():
        try:
            c = Client()
            c.cookies["sessionid"] = cookie
            barrier.wait(timeout=10)
            r = _otp(c, WRONG)
            statuses.append((r.status_code, r.content))
        except Exception as exc:  # recorded, asserted below
            errors.append(repr(exc))
        finally:
            connection.close()

    workers = [threading.Thread(target=attempt) for _ in range(threads_n)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=60)

    assert not errors, errors
    assert len(statuses) == threads_n
    voter.refresh_from_db()
    assert voter.otp_failed_attempts == LIMIT
    assert voter.otp_hash == ""
    assert AuthSecurityEvent.objects.count() == 1
    assert sum(b"Too many incorrect codes" in body for _, body in statuses) == 1
    assert not Session.objects.filter(voter=voter).exists()
