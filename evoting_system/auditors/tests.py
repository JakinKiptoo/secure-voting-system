"""
Auditor Dashboard tests.

Covers: the Auditor Role (auditor-side half of FR-OFF/AUD-01) and its
shared has_role() helper, access control against three distinct
rejected actors (anonymous, Voter-via-voter_sessions, Official-only),
the AuditLog browser (FR-AUD-01) including pagination/filtering, the
chain-integrity check (FR-AUD-02) against both an intact chain and a
deliberately corrupted one, the DPA checklist placeholder (FR-AUD-03),
and the no-leak test that actually proves guardrail #1/#2 held here
too -- modeled directly on officials/tests.py's
test_dashboard_no_voter_session_ballot_detail_leaks, same rigor.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from auditlog.models import AuditLog
from ballots.models import Ballot
from ballots.services import cast_ballot
from elections.models import Candidate, Election
from officials.permissions import OFFICIAL_GROUP_NAME
from voter_sessions.models import Session
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

from .permissions import AUDITOR_GROUP_NAME, is_auditor
from .services import verify_chain_integrity

DASHBOARD_URL_NAME = "auditors:dashboard"
AUDIT_LOG_LIST_URL_NAME = "auditors:audit_log_list"
VERIFY_CHAIN_URL_NAME = "auditors:verify_chain"
DPA_CHECKLIST_URL_NAME = "auditors:dpa_checklist"


def _make_auditor(django_user_model, username="auditor1"):
    user = django_user_model.objects.create_user(
        username=username, password="pass12345", is_staff=True
    )
    group, _ = Group.objects.get_or_create(name=AUDITOR_GROUP_NAME)
    user.groups.add(group)
    return user


def _make_official_only(django_user_model, username="official_only1"):
    user = django_user_model.objects.create_user(
        username=username, password="pass12345", is_staff=True
    )
    group, _ = Group.objects.get_or_create(name=OFFICIAL_GROUP_NAME)
    user.groups.add(group)
    return user


def _make_staff_no_role(django_user_model, username="staffer1"):
    return django_user_model.objects.create_user(
        username=username, password="pass12345", is_staff=True
    )


def _cast_one_ballot(voter_suffix="1"):
    """Creates an open election+candidate and casts one real ballot,
    returning the BallotCastResult. Used wherever a test needs a real
    AuditLog row produced the normal way, not inserted directly."""
    now = timezone.now()
    election = Election.objects.create(
        title=f"Auditor Test Election {voter_suffix}",
        start_date=now,
        end_date=now + timedelta(hours=2),
    )
    candidate = Candidate.objects.create(election=election, name="Test Candidate")
    election.open_voting()

    voter = Voter.objects.create(
        national_id_hash=sha256_hex(f"6000000{voter_suffix}"),
        full_name=f"Test Voter {voter_suffix}",
        phone_number=f"+25475000000{voter_suffix}",
    )
    session = issue_session(voter)
    return cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)


# ---------------------------------------------------------------------
# Auditor-side half of FR-OFF/AUD-01: the Role concept itself
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_auditor_group_exists_after_migrate():
    """
    The "Auditor" group is created idempotently by a post_migrate
    signal (auditors/apps.py), not a data migration -- unlike
    "Official", which officials/migrations/0001_create_official_group.py
    creates. Both end up existing after `migrate` either way; this
    test only confirms the group exists, per the test DB's own
    migrate run having already fired post_migrate.
    """
    assert Group.objects.filter(name=AUDITOR_GROUP_NAME).exists()


@pytest.mark.django_db
def test_is_auditor_requires_both_staff_and_group_membership(django_user_model):
    user = django_user_model.objects.create_user(
        username="nonstaff", password="pass12345", is_staff=False
    )
    group, _ = Group.objects.get_or_create(name=AUDITOR_GROUP_NAME)
    user.groups.add(group)

    assert is_auditor(user) is False


@pytest.mark.django_db
def test_is_auditor_requires_group_not_just_staff(django_user_model):
    user = _make_staff_no_role(django_user_model)
    assert is_auditor(user) is False


@pytest.mark.django_db
def test_is_auditor_true_for_a_real_auditor(django_user_model):
    user = _make_auditor(django_user_model)
    assert is_auditor(user) is True


@pytest.mark.django_db
def test_account_can_hold_both_official_and_auditor_roles(django_user_model):
    """No mutual exclusion between roles, per the Part 2 instruction."""
    user = _make_auditor(django_user_model, username="dual1")
    official_group, _ = Group.objects.get_or_create(name=OFFICIAL_GROUP_NAME)
    user.groups.add(official_group)

    assert is_auditor(user) is True
    from officials.permissions import is_official

    assert is_official(user) is True


# ---------------------------------------------------------------------
# Access control -- three distinct rejected actors, each its own test.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_rejects_anonymous_user(client):
    response = client.get(reverse(DASHBOARD_URL_NAME))
    assert response.status_code in (302, 403)
    if response.status_code == 302:
        assert "login" in response.url


@pytest.mark.django_db
def test_dashboard_rejects_voter_authenticated_only_via_voter_sessions(client):
    """
    Guardrail #3, exercised directly: a Voter who completed the
    OTP/voter_sessions flow is not a django.contrib.auth user, so
    request.user is AnonymousUser for them -- confirms auditor_required
    never reads anything voter_sessions writes into the session.
    """
    voter = Voter.objects.create(
        national_id_hash=sha256_hex("60000099"),
        full_name="Authenticated Voter",
        phone_number="+254750000099",
    )
    session = issue_session(voter)

    s = client.session
    s[VOTING_TOKEN_SESSION_KEY] = str(session.uuid_token)
    s.save()

    response = client.get(reverse(DASHBOARD_URL_NAME))
    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_dashboard_rejects_official_only_account(client, django_user_model):
    """
    An account holding "Official" but NOT "Auditor" must be rejected --
    the two roles are checked independently, so Official membership
    alone must never satisfy auditor_required.
    """
    user = _make_official_only(django_user_model)
    client.force_login(user)

    response = client.get(reverse(DASHBOARD_URL_NAME))
    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_rejects_staff_user_without_auditor_group(client, django_user_model):
    user = _make_staff_no_role(django_user_model)
    client.force_login(user)

    response = client.get(reverse(DASHBOARD_URL_NAME))
    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_allows_a_real_auditor(client, django_user_model):
    user = _make_auditor(django_user_model)
    client.force_login(user)

    response = client.get(reverse(DASHBOARD_URL_NAME))
    assert response.status_code == 200


# ---------------------------------------------------------------------
# FR-AUD-01: AuditLog browser -- filtering, pagination, zero entries
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_audit_log_list_handles_zero_entries(client, django_user_model):
    client.force_login(_make_auditor(django_user_model))

    assert AuditLog.objects.count() == 0
    response = client.get(reverse(AUDIT_LOG_LIST_URL_NAME))

    assert response.status_code == 200
    assert "no audit log entries" in response.content.decode().lower()


@pytest.mark.django_db
def test_audit_log_list_shows_cast_entries(client, django_user_model):
    client.force_login(_make_auditor(django_user_model))

    result = _cast_one_ballot("2")

    response = client.get(reverse(AUDIT_LOG_LIST_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert result.audit_entry.ballot_hash in body
    assert "ballot_cast" in body


@pytest.mark.django_db
def test_audit_log_list_filters_by_action_type(client, django_user_model):
    client.force_login(_make_auditor(django_user_model))

    result = _cast_one_ballot("3")
    # A second, differently-typed entry that should be filtered out.
    AuditLog.objects.create(
        ballot=Ballot.objects.create(
            election=result.ballot.election, candidate=result.ballot.candidate
        ),
        action_type="manual_review",
        ballot_hash="deadbeef",
        previous_hash=result.audit_entry.ballot_hash,
    )

    response = client.get(reverse(AUDIT_LOG_LIST_URL_NAME), {"action_type": "manual_review"})
    body = response.content.decode()

    assert response.status_code == 200
    assert "deadbeef" in body
    # Only the manual_review row should be present -- note its own
    # "previous hash" column legitimately shows the cast-ballot
    # entry's ballot_hash (that's the real chain value), so the
    # absence check here is on the filtered-OUT row's own identity
    # (its action_type), not the hash value it happens to reference.
    assert len(response.context["page_obj"].object_list) == 1
    assert response.context["page_obj"].object_list[0].action_type == "manual_review"
    assert "ballot_cast" not in body


@pytest.mark.django_db
def test_audit_log_list_paginates(client, django_user_model):
    client.force_login(_make_auditor(django_user_model))

    now = timezone.now()
    election = Election.objects.create(
        title="Pagination Election", start_date=now, end_date=now + timedelta(hours=2)
    )
    candidate = Candidate.objects.create(election=election, name="Candidate")

    previous_hash = ""
    for i in range(30):
        ballot = Ballot.objects.create(election=election, candidate=candidate)
        entry = AuditLog.objects.create(
            ballot=ballot,
            action_type="ballot_cast",
            ballot_hash=f"hash{i:03d}",
            previous_hash=previous_hash,
        )
        previous_hash = entry.ballot_hash

    response_page1 = client.get(reverse(AUDIT_LOG_LIST_URL_NAME))
    assert response_page1.status_code == 200
    assert len(response_page1.context["page_obj"].object_list) == 25

    response_page2 = client.get(reverse(AUDIT_LOG_LIST_URL_NAME), {"page": 2})
    assert response_page2.status_code == 200
    assert len(response_page2.context["page_obj"].object_list) == 5


# ---------------------------------------------------------------------
# FR-AUD-02: chain integrity check
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_verify_chain_integrity_reports_intact_for_a_real_chain():
    """Several real ballots cast in sequence via cast_ballot() must
    chain correctly, since cast_ballot() itself builds previous_hash
    from the prior entry -- this proves the checker agrees with the
    production write path, not just a hand-built fixture."""
    _cast_one_ballot("4")
    _cast_one_ballot("5")
    _cast_one_ballot("6")

    result = verify_chain_integrity()

    assert result.intact is True
    assert result.entries_checked == 3


@pytest.mark.django_db
def test_verify_chain_integrity_reports_no_entries():
    result = verify_chain_integrity()
    assert result.intact is True
    assert result.entries_checked == 0


@pytest.mark.django_db
def test_verify_chain_integrity_detects_a_deliberately_corrupted_row():
    """
    Casts three real ballots, then reaches directly into the ORM
    (bypassing cast_ballot() entirely) to corrupt the middle entry's
    previous_hash -- proving the checker actually detects a broken
    chain, not just that it can confirm an already-intact one.
    """
    _cast_one_ballot("7")
    r2 = _cast_one_ballot("8")
    _cast_one_ballot("9")

    middle_entry = r2.audit_entry
    middle_entry.previous_hash = "tampered-value-0000000000000000000000000000000000000000000"
    middle_entry.save(update_fields=["previous_hash"])

    result = verify_chain_integrity()

    assert result.intact is False
    assert result.break_log_id == middle_entry.log_id
    assert result.actual_previous_hash == "tampered-value-0000000000000000000000000000000000000000000"


@pytest.mark.django_db
def test_verify_chain_view_renders_break_position(client, django_user_model):
    client.force_login(_make_auditor(django_user_model))

    r1 = _cast_one_ballot("10")
    r2 = _cast_one_ballot("11")  # r2.previous_hash == r1's ORIGINAL ballot_hash

    # Corrupt r1's ballot_hash AFTER r2 already chained from its
    # original value -- this is what actually breaks self-consistency
    # (r2.previous_hash no longer matches r1's current ballot_hash),
    # unlike changing a row's own hash before anything else reads it.
    r1.audit_entry.ballot_hash = "corrupted-hash"
    r1.audit_entry.save(update_fields=["ballot_hash"])

    response = client.get(reverse(VERIFY_CHAIN_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert "broken" in body.lower()
    assert str(r2.audit_entry.log_id) in body


# ---------------------------------------------------------------------
# FR-AUD-03: DPA 2019 checklist -- placeholder only, no fabricated data
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_dpa_checklist_shows_sprint5_not_complete_placeholder(client, django_user_model):
    client.force_login(_make_auditor(django_user_model))

    response = client.get(reverse(DPA_CHECKLIST_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert response.context["checklist_available"] is False
    assert "not yet complete" in body.lower()


# ---------------------------------------------------------------------
# The important test: no per-voter/session/ballot-identity detail
# leaks, modeled directly on officials/tests.py's
# test_dashboard_no_voter_session_ballot_detail_leaks -- same rigor.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_audit_log_list_no_voter_session_ballot_identity_leaks(client, django_user_model):
    """
    Casts a real ballot with distinctive, identifiable values first,
    then asserts none of those values appear anywhere in the Auditor
    dashboard's AuditLog browser -- neither in its rendered HTML nor
    in its context data -- EXCEPT ballot_hash, which FR-AUD-01
    explicitly requires this page to display. Everything that could
    tie a hash back to a specific voter, session, or Ballot row
    identity must still be absent: raw ballot_id, voter name/phone/
    national ID (raw and hashed), and the session token/pk.
    """
    client.force_login(_make_auditor(django_user_model))

    now = timezone.now()
    election = Election.objects.create(
        title="Auditor Leak Check Election", start_date=now, end_date=now + timedelta(hours=2)
    )
    candidate = Candidate.objects.create(election=election, name="Leak Check Candidate")
    election.open_voting()

    distinctive_name = "Zzyzx Nakamura-Odongo"
    distinctive_phone = "+254799999998"
    distinctive_national_id = "99997777"

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

    response = client.get(reverse(AUDIT_LOG_LIST_URL_NAME))
    assert response.status_code == 200
    body = response.content.decode()

    # Legitimately displayed by FR-AUD-01 -- must be present, not forbidden.
    assert distinctive_audit_hash in body

    forbidden_values = [
        distinctive_name,
        distinctive_phone,
        distinctive_national_id,
        sha256_hex(distinctive_national_id),
        distinctive_token,
        distinctive_session_pk,
        distinctive_ballot_id,
    ]
    for leak in forbidden_values:
        assert leak not in body, f"Leaked into rendered HTML: {leak!r}"

    # Context data itself: no Voter/Session/Ballot model instance
    # anywhere, and never a raw Ballot pk -- not just absent from the
    # rendered HTML, absent from the data the view handed the
    # template in the first place.
    context = response.context
    forbidden_types = (Voter, Session, Ballot)

    def _check(value, path):
        assert not isinstance(value, forbidden_types), (
            f"context[{path!r}] holds a {type(value).__name__} instance"
        )
        if isinstance(value, str):
            for leak in forbidden_values:
                assert leak != value, f"context[{path!r}] holds forbidden value {leak!r}"
        if isinstance(value, dict):
            for k, v in value.items():
                _check(v, f"{path}.{k}")
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                _check(item, f"{path}[{i}]")

    for key in context.keys():
        _check(context.get(key), key)


@pytest.mark.django_db
def test_verify_chain_view_no_voter_session_ballot_identity_leaks(client, django_user_model):
    """Same guarantee, for the chain-verification view: it reports
    log_id/timestamp/hash values only, never anything Voter/Session/
    Ballot-identifying."""
    client.force_login(_make_auditor(django_user_model))

    distinctive_name = "Qiao Vandenberg-Mutiso"
    distinctive_phone = "+254799999997"
    distinctive_national_id = "99996666"

    voter = Voter.objects.create(
        national_id_hash=sha256_hex(distinctive_national_id),
        full_name=distinctive_name,
        phone_number=distinctive_phone,
    )
    now = timezone.now()
    election = Election.objects.create(
        title="Chain Leak Check Election", start_date=now, end_date=now + timedelta(hours=2)
    )
    candidate = Candidate.objects.create(election=election, name="Candidate")
    election.open_voting()
    session = issue_session(voter)
    distinctive_token = str(session.uuid_token)

    result = cast_ballot(uuid_token=distinctive_token, candidate_id=candidate.candidate_id)
    distinctive_ballot_id = str(result.ballot.ballot_id)

    response = client.get(reverse(VERIFY_CHAIN_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    for leak in [
        distinctive_name,
        distinctive_phone,
        distinctive_national_id,
        sha256_hex(distinctive_national_id),
        distinctive_token,
        distinctive_ballot_id,
    ]:
        assert leak not in body, f"Leaked into rendered HTML: {leak!r}"
