"""
Concurrency between casting ballots and closing / publishing an election
(FR-A-03 voting period, FR-EL-03 publish step, FR-V-04..07 cast transaction).

Invariant under test: every ballot that cast_ballot() accepted is in the
tally that publish_results() published, and an election is published at
most once. Threads use their own database connections with real commits,
in the style of ballots/test_concurrency.py.
"""

import threading
import time
from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.utils import timezone

from ballots import services as ballot_services
from ballots.models import Ballot
from ballots.services import BallotCastError, cast_ballot
from elections.models import Candidate, Election
from tally import services as tally_services
from tally.models import ElectionResult
from tally.services import publish_results
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

NOT_OPEN = "This election is not currently open for voting."


def _open_election(voters):
    now = timezone.now()
    election = Election.objects.create(title="Race Election", start_date=now, end_date=now + timedelta(hours=2))
    cands = [Candidate.objects.create(election=election, name=f"Race Candidate {i}") for i in range(2)]
    election.open_voting()
    tokens = []
    for i in range(voters):
        v = Voter.objects.create(national_id_hash=sha256_hex(f"7600{i:04d}"), full_name=f"Race Voter {i}",
                                 phone_number=f"+2547600{i:05d}")
        tokens.append(str(issue_session(v).uuid_token))
    return election, cands, tokens


def _close_and_publish(election_id, out):
    try:
        Election.objects.get(pk=election_id).close_voting()
        publish_results(Election.objects.get(pk=election_id))
        out["published"] = True
    except Exception as exc:  # recorded, asserted by the caller
        out["error"] = repr(exc)
    finally:
        connection.close()


def _assert_accepted_ballots_are_in_published_tally(election, accepted):
    result = ElectionResult.objects.get(election=election)
    stored = Ballot.objects.filter(election=election).count()
    assert stored == accepted, f"{accepted} casts accepted but {stored} ballots stored"
    assert result.total_ballots == stored, (
        f"published total_ballots={result.total_ballots} but {stored} accepted ballots are stored"
    )
    assert sum(result.candidate_counts.values()) == stored


@pytest.mark.django_db(transaction=True)
def test_fr_a03_fr_el03_cast_in_flight_during_close_and_publish_is_counted_or_rejected(monkeypatch):
    """T1: a cast that has passed the open check is held inside its transaction while another
    connection closes and publishes the election; then the cast is released."""
    election, cands, (token,) = _open_election(1)
    passed_open_check, release = threading.Event(), threading.Event()
    real_hash = ballot_services._compute_ballot_hash

    def held(*args, **kwargs):  # step 3, after the open check and the Ballot insert
        passed_open_check.set()
        release.wait(timeout=20)
        return real_hash(*args, **kwargs)

    monkeypatch.setattr(ballot_services, "_compute_ballot_hash", held)
    cast_out, closer_out = {}, {}

    def cast():
        try:
            cast_ballot(uuid_token=token, candidate_id=cands[0].candidate_id)
            cast_out["accepted"] = True
        except BallotCastError as exc:
            cast_out["rejected"] = str(exc)
        except Exception as exc:
            cast_out["error"] = repr(exc)
        finally:
            connection.close()

    t_cast = threading.Thread(target=cast)
    t_cast.start()
    assert passed_open_check.wait(timeout=20)
    t_close = threading.Thread(target=_close_and_publish, args=(election.election_id, closer_out))
    t_close.start()
    t_close.join(timeout=5)  # give close + publish time to run while the cast is held
    release.set()
    t_cast.join(timeout=60)
    t_close.join(timeout=60)

    assert "error" not in cast_out and "error" not in closer_out, (cast_out, closer_out)
    assert closer_out.get("published") is True
    _assert_accepted_ballots_are_in_published_tally(election, accepted=1 if cast_out.get("accepted") else 0)


def _two_simultaneous_publishes(monkeypatch):
    election, cands, tokens = _open_election(3)
    for i, token in enumerate(tokens):
        cast_ballot(uuid_token=token, candidate_id=cands[i % 2].candidate_id)
    election.close_voting()

    real_compute = tally_services.compute_tally

    def slow_compute(*args, **kwargs):  # widen the window between the checks and the insert
        time.sleep(0.3)
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(tally_services, "compute_tally", slow_compute)
    barrier = threading.Barrier(2)
    outcomes = []

    def publish():
        try:
            barrier.wait(timeout=10)
            publish_results(Election.objects.get(pk=election.election_id))
            outcomes.append("published")
        except (ValidationError, IntegrityError) as exc:
            outcomes.append(type(exc).__name__)
        except Exception as exc:
            outcomes.append("unexpected " + repr(exc))
        finally:
            connection.close()

    threads = [threading.Thread(target=publish) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    print("T2 outcomes:", sorted(outcomes))
    return election, outcomes


@pytest.mark.django_db(transaction=True)
def test_fr_el03_two_simultaneous_publishes_produce_exactly_one_publication(monkeypatch):
    """T2: two publish calls for one CLOSED election, started together."""
    election, outcomes = _two_simultaneous_publishes(monkeypatch)
    assert sorted(outcomes).count("published") == 1, outcomes
    assert all(o in ("published", "ValidationError", "IntegrityError") for o in outcomes), outcomes
    assert ElectionResult.objects.filter(election=election).count() == 1
    _assert_accepted_ballots_are_in_published_tally(election, accepted=3)


@pytest.mark.django_db(transaction=True)
def test_fr_el03_losing_concurrent_publish_gets_the_already_published_error(monkeypatch):
    """T2b: the second of two simultaneous publishes gets the normal ValidationError
    (which publish_results_view shows on the page), not a database IntegrityError
    (which that view does not catch)."""
    election, outcomes = _two_simultaneous_publishes(monkeypatch)
    assert sorted(outcomes) == ["ValidationError", "published"], outcomes


@pytest.mark.django_db(transaction=True)
def test_fr_a03_fr_el03_ten_casts_racing_a_close_are_all_in_the_published_tally(monkeypatch):
    """T3: 10 casts (10 voters) racing one close + publish."""
    election, cands, tokens = _open_election(10)
    real_hash = ballot_services._compute_ballot_hash

    def slow(*args, **kwargs):
        time.sleep(0.05)
        return real_hash(*args, **kwargs)

    monkeypatch.setattr(ballot_services, "_compute_ballot_hash", slow)
    barrier = threading.Barrier(11)
    accepted, rejected, errors, closer_out = [], [], [], {}

    def cast(token, cand):
        try:
            barrier.wait(timeout=10)
            cast_ballot(uuid_token=token, candidate_id=cand.candidate_id)
            accepted.append(token)
        except BallotCastError as exc:
            rejected.append(str(exc))
        except Exception as exc:
            errors.append(repr(exc))
        finally:
            connection.close()

    def closer():
        barrier.wait(timeout=10)
        time.sleep(0.1)  # let some casts get past their open check first
        _close_and_publish(election.election_id, closer_out)

    threads = [threading.Thread(target=cast, args=(t, cands[i % 2])) for i, t in enumerate(tokens)]
    threads.append(threading.Thread(target=closer))
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=120)

    assert not errors, errors
    assert "error" not in closer_out, closer_out
    assert set(rejected) <= {NOT_OPEN}, rejected
    assert len(accepted) + len(rejected) == 10
    _assert_accepted_ballots_are_in_published_tally(election, accepted=len(accepted))
