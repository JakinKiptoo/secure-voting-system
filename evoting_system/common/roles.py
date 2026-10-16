"""
Shared, group-name-keyed role-check helpers for staff-side dashboards
(Officials, Auditors, and any future role-gated internal dashboard).

Extracted from officials/permissions.py (Thread A, Part 1) during
Part 2 (Auditor Dashboard) so the same is_authenticated-and-is_staff-
and-group-membership pattern isn't duplicated a second time with a
new bespoke function. Lives in this small, model-less `common/`
package at the project root -- not inside `officials/` or
`auditors/` -- specifically so neither app has to import the other's
internals to share it; both import from here instead. `common/` needs
no entry in INSTALLED_APPS: it defines no models, migrations, or
admin registrations, so Django doesn't need to know about it as an
app to import a plain module from it.

An account can hold more than one role (be in both "Official" and
"Auditor") -- has_role() checks one group name at a time and doesn't
enforce exclusivity between roles; callers combine checks themselves
if a view ever needs "either role" or "both roles" logic.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.urls import reverse


def has_role(user, group_name: str) -> bool:
    """
    True only for an authenticated, is_staff Django user who also
    belongs to the named Group. False for AnonymousUser -- and
    therefore false for a Voter authenticated only via the
    voter_sessions/OTP flow, since that flow never touches
    django.contrib.auth at all (request.user is AnonymousUser for
    them too, exactly like a never-logged-in visitor).

    is_staff is required in addition to group membership -- not
    because Django enforces that relationship automatically (it
    doesn't; a Group can hold a non-staff user), but so that:
      (a) a role can never be granted to a user who can't log into
          /admin/ at all, which would make any admin-backed quick-link
          action unusable for them, and
      (b) "is_staff but not in the group" (a plain Django staff
          account) is cleanly distinguishable from "is_staff and in
          the group" by this one predicate.
    """
    return (
        user.is_authenticated
        and user.is_staff
        and user.groups.filter(name=group_name).exists()
    )


def role_required(group_name: str, forbidden_message: str):
    """
    Decorator factory for role-gated dashboard views. The returned
    decorator behaves identically to Part 1's official_required:
      - not authenticated at all (anonymous, or a Voter whose only
        "login" is a voter_sessions token in the browser session --
        django.contrib.auth never sees that) -> redirected to the
        admin login, same as any other unauthenticated request to a
        Django-auth-gated page.
      - authenticated but missing the named group (e.g. a plain Django
        staff account, or an account holding a *different* role only)
        -> 403 Forbidden (PermissionDenied) -- they ARE logged in,
        just not authorized for this role, so a redirect-to-login
        would be the wrong signal.

    `forbidden_message` is the exact PermissionDenied message raised
    on the second case -- passed explicitly per call site rather than
    built from `group_name` here, so each dashboard keeps its own
    wording (e.g. "election officials" vs "compliance auditors")
    without this shared module guessing at phrasing.
    """

    def decorator(view_func):
        @wraps(view_func)
        def _wrapped(request, *args, **kwargs):
            if not request.user.is_authenticated:
                return redirect_to_login(
                    request.get_full_path(), login_url=reverse("admin:login")
                )
            if not has_role(request.user, group_name):
                raise PermissionDenied(forbidden_message)
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator
