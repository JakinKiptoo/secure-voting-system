"""
FR-NAV-01 (EXTENSIONS_ROADMAP.md): shared, role-aware navigation.

Extension ID, not a core requirement. Navigation is display only: these
tests check which links are rendered, plus that staff logout is a
CSRF-protected POST. Access control itself is still covered by each
app's own tests and re-checked at the end of this file.
"""

from datetime import timedelta

import pytest
from django.contrib.auth.models import Group
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from elections.models import Candidate, Election
from tally.services import publish_results
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session
from voters.models import Voter

NAV_MARK = 'data-testid="site-nav"'

OFFICIAL_LINKS = ["/officials/overview/", "/officials/elections/", "/officials/candidates/"]
AUDITOR_LINKS = ["/auditors/audit-log/", "/auditors/audit-log/verify/", "/auditors/compliance/"]
ANON_LINKS = ["/", "/tally/", "/voters/privacy/", "/voters/login/", "/admin/login/"]
LOGOUT_ACTION = 'action="/staff/logout/"'
END_SESSION_ACTION = 'action="/voters/end-session/"'


def _staff(django_user_model, username, group=None, is_staff=True, groups=()):
    user = django_user_model.objects.create_user(username=username, password="pass12345", is_staff=is_staff)
    for name in ([group] if group else []) + list(groups):
        user.groups.add(Group.objects.get_or_create(name=name)[0])
    return user


def _nav_hrefs(body):
    """Hrefs/actions inside the nav block only (not sidebar or page body)."""
    nav = body.split(NAV_MARK, 1)[1].split("</nav>", 1)[0]
    return nav


def _election(title="Nav Election", state="OPEN"):
    election = Election.objects.create(
        title=title, start_date=timezone.now(), end_date=timezone.now() + timedelta(hours=2)
    )
    Candidate.objects.create(election=election, name="Nav Candidate")
    if state in ("OPEN", "CLOSED"):
        election.open_voting()
    if state == "CLOSED":
        election.close_voting()
    return election


def _voter_with_token(client):
    voter = Voter.objects.create(national_id_hash="navhash", full_name="Nav Voter", phone_number="+254700000777")
    session = issue_session(voter)
    s = client.session
    s[VOTING_TOKEN_SESSION_KEY] = str(session.uuid_token)
    s.save()
    return voter, session


# ----------------------------------------------------------------------
# Presence on every page
# ----------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_nav01_navigation_is_on_every_public_and_voter_page(client):
    _election()
    published = _election("Pub", "CLOSED")
    publish_results(published)
    pages = [
        "/", "/voters/register/", "/voters/login/", "/voters/privacy/",
        "/tally/", f"/tally/{published.election_id}/",
        "/ballots/cast/",  # no token: the rejected page
    ]
    for url in pages:
        response = client.get(url)
        assert response.status_code == 200, url
        assert NAV_MARK in response.content.decode(), url


@pytest.mark.django_db
def test_fr_nav01_navigation_is_on_voter_flow_pages_after_login(client):
    _election()
    _voter_with_token(client)
    for url in ("/ballots/cast/",):
        assert NAV_MARK in client.get(url).content.decode(), url
    # OTP page (pending step), session-ended and rejected pages.
    s = client.session
    s["pending_auth_voter_id"] = "x"
    s["pending_auth_expiry"] = (timezone.now() + timedelta(minutes=5)).isoformat()
    s.save()
    response = client.get("/voters/verify-otp/")
    assert response.status_code == 200
    assert NAV_MARK in response.content.decode()


@pytest.mark.django_db
def test_fr_nav01_navigation_is_on_staff_pages(client, django_user_model):
    user = _staff(django_user_model, "both", groups=("Official", "Auditor"))
    client.force_login(user)
    election = _election("Closed", "CLOSED")
    for url in (
        "/officials/overview/", "/officials/elections/", "/officials/candidates/",
        f"/officials/elections/{election.election_id}/results/",
        "/auditors/", "/auditors/audit-log/", "/auditors/audit-log/verify/", "/auditors/compliance/",
        f"/tally/{election.election_id}/publish/", "/post-login/choose/",
    ):
        response = client.get(url)
        assert response.status_code == 200, url
        assert NAV_MARK in response.content.decode(), url


@pytest.mark.django_db
def test_fr_nav01_navigation_on_session_end_and_expired_pages(client):
    _voter_with_token(client)
    assert NAV_MARK in client.post("/voters/end-session/").content.decode()


# ----------------------------------------------------------------------
# Links per role
# ----------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_nav01_anonymous_sees_public_links_only(client):
    nav = _nav_hrefs(client.get("/").content.decode())

    for href in ANON_LINKS:
        assert f'href="{href}"' in nav
    for href in OFFICIAL_LINKS + AUDITOR_LINKS:
        assert href not in nav
    assert LOGOUT_ACTION not in nav
    assert END_SESSION_ACTION not in nav
    assert "Ballot" not in nav


@pytest.mark.django_db
def test_fr_nav01_official_sees_official_links_and_logout_only(client, django_user_model):
    client.force_login(_staff(django_user_model, "off", "Official"))

    nav = _nav_hrefs(client.get("/officials/overview/").content.decode())

    for href in OFFICIAL_LINKS + ["/tally/"]:
        assert f'href="{href}"' in nav
    assert LOGOUT_ACTION in nav
    for href in AUDITOR_LINKS + ["/voters/login/", "/admin/login/", "/voters/privacy/"]:
        assert href not in nav
    assert END_SESSION_ACTION not in nav


@pytest.mark.django_db
def test_fr_nav01_auditor_sees_auditor_links_and_logout_only(client, django_user_model):
    client.force_login(_staff(django_user_model, "aud", "Auditor"))

    nav = _nav_hrefs(client.get("/auditors/").content.decode())

    for href in AUDITOR_LINKS + ["/tally/"]:
        assert f'href="{href}"' in nav
    assert LOGOUT_ACTION in nav
    for href in OFFICIAL_LINKS + ["/voters/login/", "/admin/login/"]:
        assert href not in nav


@pytest.mark.django_db
def test_fr_nav01_plain_staff_without_a_role_sees_no_role_links(client, django_user_model):
    client.force_login(_staff(django_user_model, "plain"))

    nav = _nav_hrefs(client.get("/").content.decode())

    assert 'href="/admin/"' in nav
    assert LOGOUT_ACTION in nav
    for href in OFFICIAL_LINKS + AUDITOR_LINKS:
        assert href not in nav


@pytest.mark.django_db
def test_fr_nav01_non_staff_group_member_sees_no_role_links(client, django_user_model):
    """has_role requires is_staff: a non-staff user in the group is not shown, or let in."""
    user = _staff(django_user_model, "notstaff", "Official", is_staff=False)
    client.force_login(user)

    nav = _nav_hrefs(client.get("/").content.decode())

    for href in OFFICIAL_LINKS:
        assert href not in nav
    assert LOGOUT_ACTION not in nav


@pytest.mark.django_db
def test_fr_nav01_voter_mid_flow_sees_ballot_and_end_session_only(client):
    _election()
    _voter_with_token(client)

    nav = _nav_hrefs(client.get("/ballots/cast/").content.decode())

    assert 'href="/ballots/cast/"' in nav
    assert END_SESSION_ACTION in nav
    for href in OFFICIAL_LINKS + AUDITOR_LINKS + ["/admin/login/", "/voters/login/"]:
        assert href not in nav
    assert LOGOUT_ACTION not in nav


@pytest.mark.django_db
def test_fr_nav01_active_link_is_marked(client):
    nav = _nav_hrefs(client.get("/voters/privacy/").content.decode())

    assert 'href="/voters/privacy/" aria-current="page"' in nav


# ----------------------------------------------------------------------
# Logout is POST + CSRF
# ----------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_nav01_logout_form_is_a_post_with_csrf_token(client, django_user_model):
    client.force_login(_staff(django_user_model, "off2", "Official"))

    nav = _nav_hrefs(client.get("/officials/overview/").content.decode())
    form = nav.split(LOGOUT_ACTION, 1)[1].split("</form>", 1)[0]

    assert f'{LOGOUT_ACTION} method="post"' in nav
    assert "csrfmiddlewaretoken" in form


@pytest.mark.django_db
def test_fr_nav01_staff_logout_post_ends_the_login(client, django_user_model):
    client.force_login(_staff(django_user_model, "off3", "Official"))
    assert client.get("/officials/overview/").status_code == 200

    response = client.post("/staff/logout/")

    assert response.status_code == 302 and response["Location"] == "/"
    after = client.get("/officials/overview/")
    assert after.status_code == 302 and "/admin/login/" in after["Location"]


@pytest.mark.django_db
def test_fr_nav01_staff_logout_rejects_get(client, django_user_model):
    client.force_login(_staff(django_user_model, "off4", "Official"))

    assert client.get("/staff/logout/").status_code == 405
    assert client.get("/officials/overview/").status_code == 200  # still logged in


@pytest.mark.django_db
def test_fr_nav01_staff_logout_post_requires_csrf_token(django_user_model):
    strict = Client(enforce_csrf_checks=True)
    strict.force_login(_staff(django_user_model, "off5", "Official"))

    assert strict.post("/staff/logout/").status_code == 403
    assert strict.get("/officials/overview/").status_code == 200  # not logged out


# ----------------------------------------------------------------------
# Display only: access control unchanged
# ----------------------------------------------------------------------

@pytest.mark.django_db
def test_fr_nav01_navigation_does_not_change_access_control(client, django_user_model):
    # Anonymous: staff pages still redirect to the admin login.
    for url in ("/officials/overview/", "/auditors/audit-log/"):
        response = client.get(url)
        assert response.status_code == 302 and "/admin/login/" in response["Location"]
    # An Official still gets 403 on Auditor pages (and vice versa).
    client.force_login(_staff(django_user_model, "off6", "Official"))
    assert client.get("/auditors/audit-log/").status_code == 403
    other = Client()
    other.force_login(_staff(django_user_model, "aud2", "Auditor"))
    assert other.get("/officials/overview/").status_code == 403


@pytest.mark.django_db
def test_fr_nav01_navigation_context_holds_only_plain_values(client):
    _election()
    _voter_with_token(client)
    response = client.get("/ballots/cast/")

    context = response.context
    nav = context["site_nav"] if hasattr(context, "keys") else context.flatten()["site_nav"]
    assert set(nav) == {"links", "show_logout", "logout_url", "show_end_session", "end_session_url"}
    for link in nav["links"]:
        assert set(link) == {"label", "url", "active"}
        assert all(isinstance(v, (str, bool)) for v in link.values())
