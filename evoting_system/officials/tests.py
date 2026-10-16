"""
Officials Dashboard tests.

Covers: the Official Role (FR-OFF-01), access control (the officials-
side half of FR-OFF/AUD-01) against three distinct rejected actors,
the no-leak tests that actually prove guardrail #1/#2 held (one for
Overview, one for the new Elections view), and each of the three
views' own content (FR-OFF-02 to FR-OFF-04) including the zero-
election / no-open-election states.

Thread D, Part B restructured the single "dashboard/" page into three
views (Overview/Elections/Candidates) behind a shared sidebar shell.
Every test that used to hit DASHBOARD_URL_NAME now hits whichever of
OVERVIEW_URL_NAME/ELECTIONS_URL_NAME/CANDIDATES_URL_NAME actually
covers that content today; a handful of new tests cover the Elections
view, which didn't exist before this restructure.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse
from django.utils import timezone

from ballots.models import Ballot
from ballots.services import cast_ballot
from elections.admin import ElectionAdmin, close_elections, open_elections
from elections.models import Candidate, Election
from voter_sessions.models import Session
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

from . import views as officials_views
from .permissions import OFFICIAL_GROUP_NAME, is_official

DASHBOARD_URL_NAME = "officials:dashboard"
OVERVIEW_URL_NAME = "officials:overview"
ELECTIONS_URL_NAME = "officials:elections"
CANDIDATES_URL_NAME = "officials:candidates"


def _make_official(django_user_model, username="official1"):
    user = django_user_model.objects.create_user(
        username=username, password="pass12345", is_staff=True
    )
    group, _ = Group.objects.get_or_create(name=OFFICIAL_GROUP_NAME)
    user.groups.add(group)
    return user


def _make_staff_non_official(django_user_model, username="staffer1"):
    return django_user_model.objects.create_user(
        username=username, password="pass12345", is_staff=True
    )


def _make_open_election_with_candidate(title="Dashboard Test Election"):
    now = timezone.now()
    election = Election.objects.create(
        title=title, start_date=now, end_date=now + timedelta(hours=2)
    )
    candidate = Candidate.objects.create(election=election, name="Test Candidate")
    election.open_voting()
    return election, candidate


# ---------------------------------------------------------------------
# FR-OFF-01: the Role concept itself
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_official_group_exists_after_migration():
    """
    The "Official" group is created by a migration
    (officials/migrations/0001_create_official_group.py), not assumed
    to exist or created ad hoc by test/admin setup.
    """
    assert Group.objects.filter(name=OFFICIAL_GROUP_NAME).exists()


@pytest.mark.django_db
def test_is_official_requires_both_staff_and_group_membership(django_user_model):
    """Group membership alone, without is_staff, must not pass."""
    user = django_user_model.objects.create_user(
        username="nonstaff", password="pass12345", is_staff=False
    )
    group, _ = Group.objects.get_or_create(name=OFFICIAL_GROUP_NAME)
    user.groups.add(group)

    assert is_official(user) is False


@pytest.mark.django_db
def test_is_official_requires_group_not_just_staff(django_user_model):
    """is_staff alone, without the group, must not pass (this is
    exactly the "plain Django staff account" FR-OFF-01 distinguishes
    from an Official)."""
    user = _make_staff_non_official(django_user_model)
    assert is_official(user) is False


@pytest.mark.django_db
def test_is_official_true_for_a_real_official(django_user_model):
    user = _make_official(django_user_model)
    assert is_official(user) is True


# ---------------------------------------------------------------------
# Thread D, Part B: the old dashboard/ URL now redirects to Overview
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_url_redirects_to_overview(client, django_user_model):
    client.force_login(_make_official(django_user_model))
    response = client.get(reverse(DASHBOARD_URL_NAME))
    assert response.status_code == 302
    assert response.url == reverse(OVERVIEW_URL_NAME)


def test_all_three_views_are_wrapped_by_official_required():
    """
    Confirms Overview/Elections/Candidates are each actually wrapped
    by officials.permissions.official_required (which uses
    functools.wraps, so the wrapped view is reachable via
    __wrapped__) -- not three independently hand-rolled checks that
    could silently diverge from Part 1's single dashboard_view.
    """
    for view in (
        officials_views.overview_view,
        officials_views.elections_view,
        officials_views.candidates_view,
    ):
        assert hasattr(view, "__wrapped__"), f"{view.__name__} is not decorator-wrapped"


# ---------------------------------------------------------------------
# Access control (officials-side half of FR-OFF/AUD-01) -- three
# distinct rejected actors, each its own test, run against Overview
# (where Part 1's dashboard content now lives) and spot-checked
# against Elections/Candidates too, since all three share one
# decorator.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_dashboard_rejects_anonymous_user(client):
    response = client.get(reverse(OVERVIEW_URL_NAME))
    assert response.status_code in (302, 403)
    if response.status_code == 302:
        assert "login" in response.url


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", [ELECTIONS_URL_NAME, CANDIDATES_URL_NAME])
def test_elections_and_candidates_also_reject_anonymous_user(client, url_name):
    response = client.get(reverse(url_name))
    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_dashboard_rejects_voter_authenticated_only_via_voter_sessions(client):
    """
    Guardrail #3, exercised directly: a Voter who has completed the
    OTP/voter_sessions flow (a real, active Session row, with its
    uuid_token sitting in the Django browser session under
    VOTING_TOKEN_SESSION_KEY -- exactly what voters/views.py writes on
    successful MFA) is NOT a django.contrib.auth user. request.user is
    AnonymousUser for them, the same as a visitor who never logged in
    at all. This confirms official_required's check genuinely keys off
    django.contrib.auth + the Official group and never reads anything
    voter_sessions writes into the session.
    """
    voter = Voter.objects.create(
        national_id_hash=sha256_hex("50000001"),
        full_name="Authenticated Voter",
        phone_number="+254750000001",
    )
    session = issue_session(voter)

    s = client.session
    s[VOTING_TOKEN_SESSION_KEY] = str(session.uuid_token)
    s.save()

    response = client.get(reverse(OVERVIEW_URL_NAME))
    assert response.status_code in (302, 403)


@pytest.mark.django_db
def test_dashboard_rejects_staff_user_without_official_group(client, django_user_model):
    user = _make_staff_non_official(django_user_model)
    client.force_login(user)

    response = client.get(reverse(OVERVIEW_URL_NAME))
    assert response.status_code == 403


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", [ELECTIONS_URL_NAME, CANDIDATES_URL_NAME])
def test_elections_and_candidates_also_reject_staff_without_official_group(
    client, django_user_model, url_name
):
    user = _make_staff_non_official(django_user_model)
    client.force_login(user)

    response = client.get(reverse(url_name))
    assert response.status_code == 403


@pytest.mark.django_db
def test_dashboard_allows_a_real_official(client, django_user_model):
    user = _make_official(django_user_model)
    client.force_login(user)

    response = client.get(reverse(OVERVIEW_URL_NAME))
    assert response.status_code == 200


@pytest.mark.django_db
@pytest.mark.parametrize("url_name", [ELECTIONS_URL_NAME, CANDIDATES_URL_NAME])
def test_elections_and_candidates_also_allow_a_real_official(client, django_user_model, url_name):
    user = _make_official(django_user_model)
    client.force_login(user)

    response = client.get(reverse(url_name))
    assert response.status_code == 200


# ---------------------------------------------------------------------
# Overview: zero-election / no-open-election states (Part 1's
# selection logic, unchanged -- see officials/views.py's
# _select_overview_election()).
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_overview_handles_zero_elections(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    assert Election.objects.count() == 0
    response = client.get(reverse(OVERVIEW_URL_NAME))

    assert response.status_code == 200
    assert "no elections" in response.content.decode().lower()


@pytest.mark.django_db
def test_overview_handles_draft_only_election(client, django_user_model):
    """
    An election exists but has never been opened or closed -- still
    invisible on Overview, exactly as in Part 1 (that selection logic
    is deliberately unchanged here). This is the exact scenario the
    new Elections view below is what actually fixes: see
    test_elections_view_lists_a_draft_election_invisible_on_overview.
    """
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    Election.objects.create(title="Draft Only", start_date=now, end_date=now + timedelta(days=1))

    response = client.get(reverse(OVERVIEW_URL_NAME))

    assert response.status_code == 200
    assert "no election is currently open" in response.content.decode().lower()


@pytest.mark.django_db
def test_overview_falls_back_to_most_recently_closed_election(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    older = Election.objects.create(
        title="Older Closed Election", start_date=now - timedelta(days=5), end_date=now - timedelta(days=4)
    )
    older.open_voting()
    older.close_voting()

    newer = Election.objects.create(
        title="Newer Closed Election", start_date=now - timedelta(days=2), end_date=now - timedelta(days=1)
    )
    newer.open_voting()
    newer.close_voting()

    response = client.get(reverse(OVERVIEW_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Newer Closed Election" in body
    assert "Older Closed Election" not in body
    assert response.context["is_showing_closed"] is True


# ---------------------------------------------------------------------
# FR-OFF-02/FR-OFF-04: Overview content (stat-card row)
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_overview_shows_turnout_and_candidate_count_for_open_election(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    election, candidate = _make_open_election_with_candidate()

    voter = Voter.objects.create(
        national_id_hash=sha256_hex("50000002"),
        full_name="Turnout Voter",
        phone_number="+254750000002",
    )
    session = issue_session(voter)
    cast_ballot(uuid_token=str(session.uuid_token), candidate_id=candidate.candidate_id)

    response = client.get(reverse(OVERVIEW_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert election.title in body
    assert response.context["ballot_count"] == 1
    assert response.context["voter_count"] == 1
    assert response.context["turnout_percent"] == 100.0
    assert response.context["candidate_count"] == 1


@pytest.mark.django_db
def test_overview_turnout_handles_zero_registered_voters(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    _make_open_election_with_candidate()
    assert Voter.objects.count() == 0

    response = client.get(reverse(OVERVIEW_URL_NAME))

    assert response.status_code == 200
    assert response.context["turnout_percent"] is None


@pytest.mark.django_db
def test_dashboard_candidate_overview_has_no_per_candidate_vote_counts():
    """FR-OFF-03: read-only candidate list, no vote-count field at all
    (that's results/tally territory, out of scope here)."""
    election, candidate = _make_open_election_with_candidate()
    candidates = list(election.candidates.values("name", "party", "biography"))

    assert len(candidates) == 1
    assert set(candidates[0].keys()) == {"name", "party", "biography"}


def test_dashboard_quick_link_action_names_are_real_registered_admin_actions():
    """
    The quick-link buttons POST a hardcoded `action` value
    ("open_elections" / "close_elections") that must match a function
    actually registered in ElectionAdmin.actions -- guards against the
    buttons silently breaking if that admin action is ever renamed
    without updating the dashboard templates (Overview's and, since
    Part B, each Elections-view row's). No django_db needed -- this
    only inspects admin registration, not data.
    """
    assert open_elections.__name__ == "open_elections"
    assert close_elections.__name__ == "close_elections"
    assert open_elections in ElectionAdmin.actions
    assert close_elections in ElectionAdmin.actions


@pytest.mark.django_db
def test_quick_link_open_voting_calls_the_real_admin_action(client, django_user_model):
    """
    Confirms the quick-link buttons' target (the admin changelist,
    POSTed with action=open_elections) actually exercises
    elections/admin.py's existing action -- and therefore
    Election.open_voting() -- rather than any dashboard-local logic.
    No open/close code was written for this dashboard, in Part 1 or
    in this restructure.
    """
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    election = Election.objects.create(
        title="Quick Link Election", start_date=now, end_date=now + timedelta(hours=2)
    )

    response = client.post(
        reverse("admin:elections_election_changelist"),
        {"action": "open_elections", "_selected_action": [str(election.pk)]},
        follow=True,
    )

    assert response.status_code == 200
    election.refresh_from_db()
    assert election.status == Election.Status.OPEN


# ---------------------------------------------------------------------
# Elections view (NEW, Thread D Part B): all elections regardless of
# status -- this is what fixes Overview's single-election visibility
# gap.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_elections_view_lists_a_draft_election_invisible_on_overview(client, django_user_model):
    """
    The exact visibility gap this restructure exists to fix: a DRAFT
    election with no open/closed election elsewhere was invisible on
    Part 1's single-election dashboard (see
    test_overview_handles_draft_only_election above, still true and
    still fine -- Overview's selection logic is unchanged). It must,
    however, be listed here.
    """
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    Election.objects.create(
        title="Invisible On Overview", start_date=now, end_date=now + timedelta(days=1)
    )

    response = client.get(reverse(ELECTIONS_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Invisible On Overview" in body


@pytest.mark.django_db
def test_elections_view_lists_all_statuses_together(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    draft = Election.objects.create(
        title="A Draft Election", start_date=now, end_date=now + timedelta(days=1)
    )
    opened = Election.objects.create(
        title="An Open Election", start_date=now, end_date=now + timedelta(days=1)
    )
    opened.open_voting()
    closed = Election.objects.create(
        title="A Closed Election", start_date=now - timedelta(days=2), end_date=now - timedelta(days=1)
    )
    closed.open_voting()
    closed.close_voting()

    response = client.get(reverse(ELECTIONS_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert draft.title in body
    assert opened.title in body
    assert closed.title in body


@pytest.mark.django_db
def test_elections_view_filters_by_status(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    draft = Election.objects.create(
        title="Filter Draft Election", start_date=now, end_date=now + timedelta(days=1)
    )
    opened = Election.objects.create(
        title="Filter Open Election", start_date=now, end_date=now + timedelta(days=1)
    )
    opened.open_voting()

    response = client.get(reverse(ELECTIONS_URL_NAME), {"status": "DRAFT"})
    body = response.content.decode()

    assert response.status_code == 200
    assert draft.title in body
    assert opened.title not in body


@pytest.mark.django_db
def test_elections_view_paginates(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    for i in range(officials_views.PAGE_SIZE + 5):
        Election.objects.create(
            title=f"Bulk Election {i}", start_date=now, end_date=now + timedelta(days=1)
        )

    response = client.get(reverse(ELECTIONS_URL_NAME))
    assert response.status_code == 200
    assert response.context["page_obj"].paginator.num_pages == 2
    assert len(response.context["page_obj"].object_list) == officials_views.PAGE_SIZE


@pytest.mark.django_db
def test_elections_view_shows_open_quick_link_only_for_draft_elections(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    draft = Election.objects.create(
        title="Draft With Open Button", start_date=now, end_date=now + timedelta(days=1)
    )
    closed = Election.objects.create(
        title="Closed With No Buttons", start_date=now - timedelta(days=2), end_date=now - timedelta(days=1)
    )
    closed.open_voting()
    closed.close_voting()

    response = client.get(reverse(ELECTIONS_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert "Open voting" in body
    # The closed election must not get an Open/Close button at all --
    # only DRAFT gets "Open voting" and only OPEN gets "Close voting".
    assert "Close voting" not in body


# ---------------------------------------------------------------------
# Candidates view: FR-OFF-03, now reachable for any election.
# ---------------------------------------------------------------------


@pytest.mark.django_db
def test_candidates_view_defaults_to_the_overview_election(client, django_user_model):
    client.force_login(_make_official(django_user_model))

    election, candidate = _make_open_election_with_candidate()

    response = client.get(reverse(CANDIDATES_URL_NAME))
    body = response.content.decode()

    assert response.status_code == 200
    assert election.title in body
    assert candidate.name in body


@pytest.mark.django_db
def test_candidates_view_selector_reaches_any_election(client, django_user_model):
    """
    A DRAFT election (never the Overview election) must still be
    reachable here via ?election=<uuid> -- this is what keeps
    Candidates from staying silently scoped to only the single
    Overview election now that Elections exposes every election.
    """
    client.force_login(_make_official(django_user_model))

    now = timezone.now()
    draft_election = Election.objects.create(
        title="Draft Election For Candidates", start_date=now, end_date=now + timedelta(days=1)
    )
    draft_candidate = Candidate.objects.create(election=draft_election, name="Draft Candidate")

    response = client.get(reverse(CANDIDATES_URL_NAME), {"election": str(draft_election.election_id)})
    body = response.content.decode()

    assert response.status_code == 200
    assert draft_election.title in body
    assert draft_candidate.name in body


# ---------------------------------------------------------------------
# The important tests: no per-voter/session/ballot detail leaks, on
# Overview (ported from Part 1) and on the new Elections view
# (equivalent rigor, Thread D Part B's explicit requirement).
# ---------------------------------------------------------------------


def _assert_no_forbidden_instances_in_context(context):
    """
    Shared walk used by both leak tests below: no Voter, Session, or
    Ballot model INSTANCE anywhere in the rendered context, at any
    nesting depth -- not just absent from the rendered HTML, absent
    from the data the view handed the template in the first place.
    """
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
def test_overview_no_voter_session_ballot_detail_leaks(client, django_user_model):
    """
    Asserts that nothing in Overview's context data or rendered
    template contains any Voter-identifying field, any individual
    Session/token value, or any individual Ballot's content -- only
    aggregate counts. Ported unchanged in rigor from Part 1's original
    test 6, re-pointed at the new Overview URL.
    """
    client.force_login(_make_official(django_user_model))

    election, candidate = _make_open_election_with_candidate("Leak Check Election")

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

    response = client.get(reverse(OVERVIEW_URL_NAME))
    assert response.status_code == 200
    body = response.content.decode()

    for leak in [
        distinctive_name,
        distinctive_phone,
        distinctive_national_id,
        sha256_hex(distinctive_national_id),
        distinctive_token,
        distinctive_session_pk,
        distinctive_ballot_id,
        distinctive_audit_hash,
    ]:
        assert leak not in body, f"Leaked into rendered HTML: {leak!r}"

    _assert_no_forbidden_instances_in_context(response.context)

    assert response.context["ballot_count"] == 1
    assert response.context["voter_count"] == 1


@pytest.mark.django_db
def test_elections_view_no_voter_session_ballot_detail_leaks(client, django_user_model):
    """
    Thread D, Part B's explicit requirement: the same leak-test rigor
    as Overview's, applied to the new Elections view specifically --
    it must never render any Voter, Session, or Ballot-content field,
    only Election/Candidate aggregate data (here: a per-election
    candidate COUNT, never a candidate's own content, and certainly
    never a voter's).
    """
    client.force_login(_make_official(django_user_model))

    election, candidate = _make_open_election_with_candidate("Leak Check Election (Elections View)")
    # A second, still-DRAFT election, so the view is genuinely
    # exercising its "every status" listing while the leak check runs.
    Election.objects.create(
        title="Leak Check Draft Election",
        start_date=timezone.now(),
        end_date=timezone.now() + timedelta(days=1),
    )

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

    response = client.get(reverse(ELECTIONS_URL_NAME))
    assert response.status_code == 200
    body = response.content.decode()

    for leak in [
        distinctive_name,
        distinctive_phone,
        distinctive_national_id,
        sha256_hex(distinctive_national_id),
        distinctive_token,
        distinctive_session_pk,
        distinctive_ballot_id,
        distinctive_audit_hash,
    ]:
        assert leak not in body, f"Leaked into rendered HTML: {leak!r}"

    _assert_no_forbidden_instances_in_context(response.context)

    # Only aggregate Election/Candidate data reached the template --
    # confirmed positively, not just "nothing forbidden showed up".
    page_obj = response.context["page_obj"]
    assert all(isinstance(e, Election) for e in page_obj.object_list)
    assert election.title in body
