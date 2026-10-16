"""
Thread A, Part 3: staff post-login auto-redirect -- the role-checking
half. See common/admin_login.py for why a custom login view (not just
this setting) is needed to actually reach this view after a normal
/admin/login/ submission.

This is reached ONLY by a staff user who just authenticated through
Django's ordinary django.contrib.auth login machinery (the same
single staff login the project already had -- no new credential type
or session mechanism introduced here). It is never reached by the
anonymous Voter/OTP flow: that flow never calls
django.contrib.auth.login() at all, so settings.LOGIN_REDIRECT_URL
(which points here) is never consulted for a Voter. voters/ and
voter_sessions/ are not imported or touched by this module.

"Official" and "Auditor" are repeated here as plain strings rather
than imported from officials.permissions.OFFICIAL_GROUP_NAME /
auditors.permissions.AUDITOR_GROUP_NAME -- both of those modules
already import FROM common.roles, so importing back from either of
them here would be a circular import. If either group's name is ever
renamed, this file must be updated alongside it (flagged here
deliberately, not hidden).
"""

from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from .roles import has_role

OFFICIAL_GROUP_NAME = "Official"
AUDITOR_GROUP_NAME = "Auditor"


@login_required(login_url="admin:login")
def post_login_redirect_view(request):
    """
    settings.LOGIN_REDIRECT_URL's target. Checks the just-logged-in
    user's roles via common.roles.has_role() (the same shared helper
    officials/ and auditors/ use for access control) and sends them
    straight to the dashboard that role is for:
      - Official only  -> officials:dashboard
      - Auditor only   -> auditors:dashboard
      - Both           -> a minimal chooser page (post_login_choose
        below) -- deliberately not a guess at which one they want
        right now.
      - Neither role (e.g. a superuser/plain staff account that
        predates this feature, or one with no group assigned yet)
        -> admin:index, i.e. exactly where they would have landed
        before this feature existed. Existing admin-only accounts are
        therefore unaffected.
    """
    user = request.user
    is_official = has_role(user, OFFICIAL_GROUP_NAME)
    is_auditor = has_role(user, AUDITOR_GROUP_NAME)

    if is_official and is_auditor:
        return redirect("post_login_choose")
    if is_official:
        return redirect("officials:dashboard")
    if is_auditor:
        return redirect("auditors:dashboard")
    return redirect("admin:index")


@login_required(login_url="admin:login")
def post_login_choose_view(request):
    """Shown only to an account holding both Official and Auditor --
    two plain links, nothing else. Re-checks both roles itself
    (rather than trusting a caller) so this page 403s like any other
    role-gated page if reached directly by someone without both."""
    user = request.user
    if not (has_role(user, OFFICIAL_GROUP_NAME) and has_role(user, AUDITOR_GROUP_NAME)):
        from django.core.exceptions import PermissionDenied

        raise PermissionDenied("This page is only for accounts holding both roles.")
    return render(request, "common/post_login_choose.html")
