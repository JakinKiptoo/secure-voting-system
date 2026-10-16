"""
Thread A, Part 3 tests: staff post-login auto-redirect.

Exercises the real /admin/login/ POST -> redirect chain through
Django's test client, not just the view function in isolation, so
this proves the actual URL wiring (StaffLoginView mounted ahead of
admin.site.urls, LOGIN_REDIRECT_URL pointing at post_login_redirect)
works end to end.

File named test_staff_login_redirect.py (not tests.py) because
common/ is a plain package, not a Django app -- discovered via
pytest.ini's python_files pattern ("test_*.py" is one of the
configured patterns), the same way as any other test module here.
"""

import pytest
from django.contrib.auth.models import Group
from django.urls import reverse

ADMIN_LOGIN_URL = "/admin/login/"
PASSWORD = "pass12345"


def _make_staff(django_user_model, username, groups=()):
    user = django_user_model.objects.create_user(
        username=username, password=PASSWORD, is_staff=True
    )
    for group_name in groups:
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
    return user


@pytest.mark.django_db
def test_official_only_login_redirects_to_officials_dashboard(client, django_user_model):
    _make_staff(django_user_model, "redir_official", groups=["Official"])

    response = client.post(ADMIN_LOGIN_URL, {"username": "redir_official", "password": PASSWORD})
    assert response.status_code == 302
    assert response.url == reverse("post_login_redirect")

    response2 = client.get(response.url)
    assert response2.status_code == 302
    assert response2.url == reverse("officials:dashboard")


@pytest.mark.django_db
def test_auditor_only_login_redirects_to_auditor_dashboard(client, django_user_model):
    _make_staff(django_user_model, "redir_auditor", groups=["Auditor"])

    response = client.post(ADMIN_LOGIN_URL, {"username": "redir_auditor", "password": PASSWORD})
    assert response.status_code == 302
    assert response.url == reverse("post_login_redirect")

    response2 = client.get(response.url)
    assert response2.status_code == 302
    assert response2.url == reverse("auditors:dashboard")


@pytest.mark.django_db
def test_both_roles_login_redirects_to_chooser(client, django_user_model):
    _make_staff(django_user_model, "redir_both", groups=["Official", "Auditor"])

    response = client.post(ADMIN_LOGIN_URL, {"username": "redir_both", "password": PASSWORD})
    response2 = client.get(response.url)

    assert response2.status_code == 302
    assert response2.url == reverse("post_login_choose")

    # The chooser page itself renders, with links to both dashboards.
    response3 = client.get(response2.url)
    assert response3.status_code == 200
    body = response3.content.decode()
    assert reverse("officials:dashboard") in body
    assert reverse("auditors:dashboard") in body


@pytest.mark.django_db
def test_no_role_staff_login_still_reaches_admin_index(client, django_user_model):
    """A plain staff/superuser account with neither role must land
    exactly where it would have before this feature existed."""
    _make_staff(django_user_model, "redir_noroles", groups=())

    response = client.post(ADMIN_LOGIN_URL, {"username": "redir_noroles", "password": PASSWORD})
    assert response.status_code == 302
    assert response.url == reverse("post_login_redirect")

    response2 = client.get(response.url)
    assert response2.status_code == 302
    assert response2.url == reverse("admin:index")

    response3 = client.get(response2.url)
    assert response3.status_code == 200


@pytest.mark.django_db
def test_chooser_page_rejects_single_role_account(client, django_user_model):
    """Reaching /post-login/choose/ directly without BOTH roles 403s,
    same rigor as any other role-gated page -- not reachable by
    guessing the URL."""
    _make_staff(django_user_model, "redir_official_only_direct", groups=["Official"])
    client.login(username="redir_official_only_direct", password=PASSWORD)

    response = client.get(reverse("post_login_choose"))
    assert response.status_code == 403


@pytest.mark.django_db
def test_post_login_redirect_rejects_anonymous_user(client):
    response = client.get(reverse("post_login_redirect"))
    assert response.status_code == 302
    assert "login" in response.url


@pytest.mark.django_db
def test_admin_login_override_still_resolves_under_admin_login_name():
    """reverse("admin:login") -- used by common/roles.py's
    role_required for unauthenticated staff-view access -- must still
    resolve to the same /admin/login/ path now served by
    StaffLoginView, not break or point elsewhere."""
    assert reverse("admin:login") == ADMIN_LOGIN_URL
