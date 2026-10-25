"""
Tally and Verification Module tests (Sprint 4).

Covers:
  - item 1: tally computation strictly scoped per election
  - item 2 (FR-EL-03): the publish-results gate -- close_voting() never
    auto-publishes, publish requires CLOSED, no re-publish, and a
    CLOSED-but-unpublished election shows "not yet available" rather
    than an empty/zero tally
  - item 3: the pairing-based ZKP is actually generated and stored
  - item 4 (FR-P-01): the public, unauthenticated endpoints (HTML and
    DRF JSON), scoped per election, returning a clear "not available"
    state rather than an error or a misleading empty tally
  - item 5 (FR-P-02): the plain-language rendering is present and
    internally consistent with the raw data
  - item 6 (FR-P-03): no path from this module's output back to an
    individual voter's choice -- same rigor as the existing leak tests
  - item 7: the chain-walk is the SAME function object auditors/ uses,
    not a second implementation
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from auditlog.models import AuditLog
from auditlog.services import verify_chain_integrity as auditlog_verify_chain_integrity
from auditors.permissions import AUDITOR_GROUP_NAME
from auditors.services import verify_chain_integrity as auditors_verify_chain_integrity
from ballots.models import Ballot
from ballots.services import cast_ballot
from elections.models import Candidate, Election
from officials.permissions import OFFICIAL_GROUP_NAME
from voter_sessions.models import Session
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

from .crypto import build_tally_proof, verify_tally_proof
from .models import ElectionResult
from .services import compute_tally, get_verification_payload, publish_results


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------


def _make_official(django_user_model, username="official1"):
    user = django_user_model.objects.create_user(
        username=username, password="pass12345", is_staff=True
    )
    group, _ = Group.objects.get_or_create(name=OFFICIAL_GROUP_NAME)
    user.groups.add(group)
    return user


def _make_auditor(django_user_model, username="auditor1"):
    user = django_user_model.objects.create_user(
        username=username, password="pass12345", is_staff=True
    )
    group, _ = Group.objects.get_or_create(name=AUDITOR_GROUP_NAME)
    user.groups.add(group)
    return user


def _make_staff_no_role(django_user_model, username="staffer1"):
    return django_user_model.objects.create_user(
        username=username, password="pass12345", is_staff=True
    )


def _election(title, now=None):
    now = now or timezone.now()
    return Election.objects.create(title=title, start_date=now, end_date=now + timedelta(hours=2))


def _cast_vote(election, candidate, national_id):
    voter = Voter.objects.create(
        national_id_hash=sha256_hex(national_id),
        full_name=f"Voter {national_id}",
        phone_number=f"+2547{national_id}",
    )
    session = issue_session(voter)
    return cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)


# ---------------------------------------------------------------------
# item 7: shared chain-walk, not a second implementation
# ---------------------------------------------------------------------


def test_chain_walk_is_shared_not_duplicated():
    """
    tally/ and auditors/ must call the exact same function object for
    "is the chain intact" -- auditors/services.py now just re-exports
    auditlog/services.py's implementation (see that file's docstring),
    and tally/services.py imports directly from auditlog/services.py
    too. This asserts object identity, not just "behaves the same",
    so a future accidental fork would fail this test immediately.
    """
    from tally import services as tally_services

    assert tally_services.verify_chain_integrity is auditlog_verify_chain_integrity
    assert auditors_verify_chain_integrity is auditlog_verify_chain_integrity


# ---------------------------------------------------------------------
# item 1: tally computation strictly scoped per election
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_compute_tally_is_scoped_to_one_election_with_two_concurrently_open_elections():
    """
    The core "not global" requirement: two elections, open at the same
    time, with DIFFERENT candidates and DIFFERENT results. Summing
    across them would be meaningless (different candidate sets) --
    this confirms compute_tally() never does that.
    """
    now = timezone.now()
    election_a = _election("Election A", now)
    a1 = Candidate.objects.create(election=election_a, name="Alice")
    a2 = Candidate.objects.create(election=election_a, name="Bob")
    election_a.open_voting()

    election_b = _election("Election B", now)
    b1 = Candidate.objects.create(election=election_b, name="Carol")
    b2 = Candidate.objects.create(election=election_b, name="Dave")
    election_b.open_voting()

    _cast_vote(election_a, a1, "10000001")
    _cast_vote(election_a, a1, "10000002")
    _cast_vote(election_a, a2, "10000003")

    _cast_vote(election_b, b1, "20000001")
    _cast_vote(election_b, b2, "20000002")
    _cast_vote(election_b, b2, "20000003")
    _cast_vote(election_b, b2, "20000004")

    tally_a = compute_tally(election_a)
    tally_b = compute_tally(election_b)

    assert tally_a.total_ballots == 3
    assert tally_a.candidate_counts == {str(a1.candidate_id): 2, str(a2.candidate_id): 1}

    assert tally_b.total_ballots == 4
    assert tally_b.candidate_counts == {str(b1.candidate_id): 1, str(b2.candidate_id): 3}

    # Different candidate sets entirely -- confirms no cross-election bleed.
    assert set(tally_a.candidate_counts) & set(tally_b.candidate_counts) == set()
    assert tally_a.total_ballots != tally_b.total_ballots


@pytest.mark.django_db
def test_compute_tally_ignores_ballots_from_other_elections_sharing_no_candidates():
    """A third, untouched election must report zero regardless of
    how many ballots exist elsewhere in the system."""
    now = timezone.now()
    busy = _election("Busy Election", now)
    candidate = Candidate.objects.create(election=busy, name="Busy Candidate")
    busy.open_voting()
    _cast_vote(busy, candidate, "30000001")

    quiet = _election("Quiet Election", now)
    Candidate.objects.create(election=quiet, name="Quiet Candidate")

    tally_quiet = compute_tally(quiet)
    assert tally_quiet.total_ballots == 0
    assert all(count == 0 for count in tally_quiet.candidate_counts.values())


# ---------------------------------------------------------------------
# item 2 (FR-EL-03): the publish-results gate
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_closing_voting_does_not_auto_publish():
    election = _election("No Auto Publish Election")
    election.open_voting()
    election.close_voting()

    assert not ElectionResult.objects.filter(election=election).exists()
    payload = get_verification_payload(election)
    assert payload.available is False


@pytest.mark.django_db
def test_publish_rejects_an_open_election():
    """
    Inferred constraint (see publish_results()'s docstring): publishing
    is only meaningful once voting is closed, since an OPEN election
    could still receive more ballots after "publishing".
    """
    election = _election("Still Open Election")
    election.open_voting()

    with pytest.raises(ValidationError):
        publish_results(election)
    assert not ElectionResult.objects.filter(election=election).exists()


@pytest.mark.django_db
def test_publish_rejects_a_draft_election():
    election = _election("Draft Election")
    with pytest.raises(ValidationError):
        publish_results(election)


@pytest.mark.django_db
def test_closed_but_unpublished_election_shows_not_available_not_empty_tally():
    """
    The exact requirement from item 2: a CLOSED-but-unpublished
    election must show "results not yet published", never an
    empty/zero tally that could be misread as a real result.
    """
    election = _election("Closed Not Published")
    election.open_voting()
    election.close_voting()

    payload = get_verification_payload(election)

    assert payload.available is False
    assert payload.total_ballots is None  # not 0 -- genuinely absent
    assert payload.candidate_results == []
    assert "not been published" in payload.reason_unavailable.lower()


@pytest.mark.django_db
def test_publish_succeeds_once_closed_and_is_then_available():
    now = timezone.now()
    election = _election("Normal Flow Election", now)
    candidate = Candidate.objects.create(election=election, name="Solo Candidate")
    election.open_voting()
    _cast_vote(election, candidate, "40000001")
    election.close_voting()

    result = publish_results(election)
    assert result.published is True
    assert result.total_ballots == 1

    payload = get_verification_payload(election)
    assert payload.available is True
    assert payload.total_ballots == 1


@pytest.mark.django_db
def test_cannot_publish_twice():
    election = _election("No Republish Election")
    election.open_voting()
    election.close_voting()

    publish_results(election)
    with pytest.raises(ValidationError):
        publish_results(election)

    # Still exactly one result row, untouched by the failed second call.
    assert ElectionResult.objects.filter(election=election).count() == 1


# ---------------------------------------------------------------------
# item 2: publish_results_view access control (Official OR Auditor,
# via has_role() -- not a new permission system)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_publish_view_rejects_anonymous_user(client):
    election = _election("Publish Access Election")
    election.open_voting()
    election.close_voting()

    response = client.post(reverse("tally:publish", args=[election.election_id]))
    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_publish_view_rejects_staff_without_either_role(client, django_user_model):
    election = _election("Publish Access Election 2")
    election.open_voting()
    election.close_voting()

    client.force_login(_make_staff_no_role(django_user_model))
    response = client.post(reverse("tally:publish", args=[election.election_id]))
    assert response.status_code == 403
    assert not ElectionResult.objects.filter(election=election).exists()


@pytest.mark.django_db
def test_publish_view_allows_an_official(client, django_user_model):
    election = _election("Publish By Official")
    election.open_voting()
    election.close_voting()

    client.force_login(_make_official(django_user_model))
    response = client.post(reverse("tally:publish", args=[election.election_id]))
    assert response.status_code == 302
    assert ElectionResult.objects.filter(election=election, published=True).exists()


@pytest.mark.django_db
def test_publish_view_allows_an_auditor():
    """Confirmed via the service layer directly (role check itself is
    exercised through the view in the two tests above); this
    double-checks the OR-combination specifically admits an
    Auditor-only account too, not just Official."""
    from django.contrib.auth import get_user_model

    from .permissions import can_publish_results

    user = get_user_model().objects.create_user(
        username="auditor_check", password="x", is_staff=True
    )
    group, _ = Group.objects.get_or_create(name=AUDITOR_GROUP_NAME)
    user.groups.add(group)

    assert can_publish_results(user) is True


@pytest.mark.django_db
def test_publish_view_rejects_a_still_open_election_with_a_rendered_error(client, django_user_model):
    election = _election("Publish Open Rejected")
    election.open_voting()

    client.force_login(_make_official(django_user_model))
    response = client.post(reverse("tally:publish", args=[election.election_id]))

    assert response.status_code == 200  # re-rendered with an error, not a redirect
    assert "closed" in response.content.decode().lower()
    assert not ElectionResult.objects.filter(election=election).exists()


# ---------------------------------------------------------------------
# item 3: the pairing-based ZKP is actually generated and stored
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_publish_stores_a_pairing_based_proof_that_independently_verifies():
    now = timezone.now()
    election = _election("Proof Storage Election", now)
    c1 = Candidate.objects.create(election=election, name="X")
    c2 = Candidate.objects.create(election=election, name="Y")
    election.open_voting()
    _cast_vote(election, c1, "50000001")
    _cast_vote(election, c1, "50000002")
    _cast_vote(election, c2, "50000003")
    election.close_voting()

    result = publish_results(election)

    assert result.commitment_total_g1
    assert result.commitment_total_g2
    assert result.candidate_commitments_g1

    from .crypto import TallyProof

    proof = TallyProof.from_dict(
        {
            "total_ballots": result.total_ballots,
            "candidate_counts": result.candidate_counts,
            "commitment_total_g1": result.commitment_total_g1,
            "commitment_total_g2": result.commitment_total_g2,
            "candidate_commitments_g1": result.candidate_commitments_g1,
        }
    )
    verification = verify_tally_proof(proof)
    assert verification.valid is True


def test_tally_proof_tamper_detection_pure_unit():
    """
    Pure crypto.py-level test (no DB): a proof whose stored commitment
    no longer matches its own plaintext numbers must fail
    verification. This is what makes "pairing-based" meaningful rather
    than decorative -- changing the plaintext total without
    regenerating the commitments is caught.
    """
    proof = build_tally_proof({"cand-a": 10, "cand-b": 5}, 15)
    assert verify_tally_proof(proof).valid is True

    proof.total_ballots = 999  # tamper with the plaintext only
    tampered = verify_tally_proof(proof)
    assert tampered.aggregation_holds is False
    assert tampered.recomputed_commitments_match is False
    assert tampered.valid is False


# ---------------------------------------------------------------------
# item 4 (FR-P-01): public, unauthenticated endpoints, per election
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_public_verify_page_requires_no_authentication(client):
    """No force_login anywhere in this test -- a bare, anonymous
    client.get() must succeed, per CLAUDE.md invariant #4."""
    election = _election("Public No Auth Election")
    response = client.get(reverse("tally:verify", args=[election.election_id]))
    assert response.status_code == 200


@pytest.mark.django_db
def test_public_api_endpoint_requires_no_authentication(client):
    election = _election("Public No Auth API Election")
    response = client.get(f"/api/tally/{election.election_id}/")
    assert response.status_code == 200
    assert response.json()["available"] is False


@pytest.mark.django_db
def test_public_verify_page_shows_not_yet_available_for_open_election(client):
    election = _election("Open Not Available")
    election.open_voting()

    response = client.get(reverse("tally:verify", args=[election.election_id]))
    body = response.content.decode().lower()

    assert response.status_code == 200
    assert "not yet published" in body
    assert "0 ballots" not in body  # never a disguised zero tally


@pytest.mark.django_db
def test_public_verify_page_and_api_scoped_to_one_election(client):
    """
    Two published elections, different results -- each election's
    public page/endpoint must only ever show its OWN tally, confirming
    item 1's scoping holds all the way out to the public surface, not
    just inside compute_tally().
    """
    now = timezone.now()
    election_a = _election("Public Scope A", now)
    a1 = Candidate.objects.create(election=election_a, name="Amina")
    election_a.open_voting()
    _cast_vote(election_a, a1, "60000001")
    _cast_vote(election_a, a1, "60000002")
    election_a.close_voting()
    publish_results(election_a)

    election_b = _election("Public Scope B", now)
    b1 = Candidate.objects.create(election=election_b, name="Brian")
    election_b.open_voting()
    _cast_vote(election_b, b1, "70000001")
    election_b.close_voting()
    publish_results(election_b)

    resp_a = client.get(reverse("tally:verify", args=[election_a.election_id]))
    resp_b = client.get(reverse("tally:verify", args=[election_b.election_id]))

    body_a = resp_a.content.decode()
    body_b = resp_b.content.decode()

    assert "Amina" in body_a and "Brian" not in body_a
    assert "Brian" in body_b and "Amina" not in body_b

    json_a = client.get(f"/api/tally/{election_a.election_id}/").json()
    json_b = client.get(f"/api/tally/{election_b.election_id}/").json()
    assert json_a["total_ballots"] == 2
    assert json_b["total_ballots"] == 1
    assert json_a["election_id"] != json_b["election_id"]


@pytest.mark.django_db
def test_api_endpoint_404s_cleanly_for_unknown_election(client):
    import uuid

    response = client.get(f"/api/tally/{uuid.uuid4()}/")
    assert response.status_code == 404


# ---------------------------------------------------------------------
# item 5 (FR-P-02): plain-language rendering, checkable without
# cryptographic expertise, consistent with the raw data
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_public_page_shows_plain_language_checks_that_match_the_raw_numbers():
    now = timezone.now()
    election = _election("Plain Language Election", now)
    c1 = Candidate.objects.create(election=election, name="Zawadi")
    c2 = Candidate.objects.create(election=election, name="Juma")
    election.open_voting()
    _cast_vote(election, c1, "80000001")
    _cast_vote(election, c1, "80000002")
    _cast_vote(election, c2, "80000003")
    election.close_voting()
    publish_results(election)

    from django.test import Client

    response = Client().get(reverse("tally:verify", args=[election.election_id]))
    body = response.content.decode()

    # The addition check must display the actual numbers, not just an
    # abstract claim -- "2 + 1 = 3" must literally be derivable from
    # the rendered candidate counts and total.
    assert "2" in body and "1" in body and "3" in body
    assert "Confirmed" in body  # aggregation_holds True -> this literal string
    assert "pairing" in body.lower()
    assert "tamper" in body.lower() or "changed" in body.lower()
    assert "cannot be used to work out how any individual" in body.lower() or \
        "cannot show you" in body.lower()


@pytest.mark.django_db
def test_deep_verify_query_param_runs_the_live_recheck(client):
    now = timezone.now()
    election = _election("Deep Verify Election", now)
    candidate = Candidate.objects.create(election=election, name="Deep Candidate")
    election.open_voting()
    _cast_vote(election, candidate, "90000001")
    election.close_voting()
    publish_results(election)

    fast = client.get(reverse("tally:verify", args=[election.election_id]))
    deep = client.get(reverse("tally:verify", args=[election.election_id]), {"reverify": "1"})

    assert "fully verified" not in fast.content.decode().lower()
    assert "fully verified" in deep.content.decode().lower()


# ---------------------------------------------------------------------
# item 6 (FR-P-03): no path to an individual voter's ballot choice
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_public_endpoint_no_voter_session_ballot_detail_leaks(client):
    """
    Same rigor as officials/tests.py's and auditors/tests.py's leak
    tests: cast a real ballot with distinctive, identifiable values,
    publish results, then assert none of those values are
    individually recoverable from either the HTML page or the JSON
    API -- not in the rendered/serialized output, and not anywhere in
    the HTML response's template context.
    """
    now = timezone.now()
    election = _election("Leak Check Election", now)
    candidate = Candidate.objects.create(election=election, name="Leak Check Candidate")
    election.open_voting()

    distinctive_name = "Zzyzx Nakamura-Odongo"
    distinctive_phone = "+254799999999"
    distinctive_national_id = "99998888"

    voter = Voter.objects.create(
        national_id_hash=sha256_hex(distinctive_national_id),
        full_name=distinctive_name,
        phone_number=distinctive_phone,
    )
    session = issue_session(voter)
    distinctive_token = str(session.uuid_token)
    distinctive_session_pk = str(session.pk)

    result = cast_ballot(uuid_token=distinctive_token, candidate_id=candidate.candidate_id)
    distinctive_ballot_id = str(result.ballot.ballot_id)
    distinctive_audit_hash = result.audit_entry.ballot_hash

    election.close_voting()
    publish_results(election)

    leaks = [
        distinctive_name,
        distinctive_phone,
        distinctive_national_id,
        sha256_hex(distinctive_national_id),
        distinctive_token,
        distinctive_session_pk,
        distinctive_ballot_id,
    ]

    html_response = client.get(reverse("tally:verify", args=[election.election_id]), {"reverify": "1"})
    html_body = html_response.content.decode()
    for leak in leaks:
        assert leak not in html_body, f"Leaked into rendered HTML: {leak!r}"
    # The audit hash itself IS meant to be shown (that's the point of
    # FR-P-01's "AuditLog hashes") -- it just must not be traceable
    # back to the voter, which the rest of this test's leak list
    # already confirms. Confirm it genuinely appears (sanity check
    # that the audit-entries section rendered at all):
    assert distinctive_audit_hash in html_body

    api_response = client.get(f"/api/tally/{election.election_id}/", {"reverify": "1"})
    api_text = api_response.content.decode()
    for leak in leaks:
        assert leak not in api_text, f"Leaked into JSON API: {leak!r}"

    # Context data itself: no Voter/Session/Ballot model INSTANCE
    # anywhere, exactly like officials/auditors' leak tests.
    context = html_response.context
    forbidden_types = (Voter, Session, Ballot)

    def _check(value, path):
        assert not isinstance(value, forbidden_types), (
            f"context[{path!r}] holds a {type(value).__name__} instance"
        )
        if isinstance(value, dict):
            for k, v in value.items():
                _check(v, f"{path}.{k}")
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                _check(item, f"{path}[{i}]")

    for key in context.keys():
        _check(context.get(key), key)


@pytest.mark.django_db
def test_candidate_level_counts_do_not_reveal_which_ballot_was_whose():
    """
    A structural check, not just a string-absence check: the
    candidate_results the public payload exposes are {id, name,
    count} only -- no per-ballot list, no timestamps, nothing that
    could be correlated with a specific voter's session timing.
    """
    now = timezone.now()
    election = _election("Structural Leak Check", now)
    candidate = Candidate.objects.create(election=election, name="Structural Candidate")
    election.open_voting()
    _cast_vote(election, candidate, "11111111")
    election.close_voting()
    publish_results(election)

    payload = get_verification_payload(election)
    for row in payload.candidate_results:
        assert set(row.keys()) == {"candidate_id", "name", "count"}


@pytest.mark.django_db
def test_tamper_after_publish_is_detected_by_deep_verify(client):
    """
    FR-P-03's neighbour guarantee (tamper-EVIDENCE, not just
    tamper-prevention): directly mutating an AuditLog row's hash after
    publication -- simulating a compromise below the application layer
    -- must be caught by the deep-verify path, since that's the whole
    point of binding the proof to a digest of this election's audit
    entries.
    """
    now = timezone.now()
    election = _election("Tamper Detection Election", now)
    candidate = Candidate.objects.create(election=election, name="Tamper Candidate")
    election.open_voting()
    _cast_vote(election, candidate, "22222222")
    election.close_voting()
    publish_results(election)

    entry = AuditLog.objects.filter(ballot__election=election).first()
    entry.ballot_hash = "0" * 64
    entry.save(update_fields=["ballot_hash"])

    payload = get_verification_payload(election, deep_verify=True)
    assert payload.verification["audit_entries_unchanged"] is False
    assert payload.verification["fully_verified"] is False
