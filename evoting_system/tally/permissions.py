"""
Access control for the one authenticated action in this module:
publishing an election's results (FR-EL-03). Every other view in
tally/ (the public verification endpoint) is deliberately
unauthenticated -- see views.py -- per CLAUDE.md invariant #4.

Sprint 4 prompt, item 2: "Official or Auditor role, via the existing
has_role() helper, not a new permission check." common/roles.py's own
docstring already anticipates exactly this: "An account can hold more
than one role... has_role() checks one group name at a time... callers
combine checks themselves if a view ever needs 'either role' or 'both
roles' logic." publisher_required below is that combination -- built
the same way officials/permissions.py and auditors/permissions.py each
wrap has_role() for their own single role, just OR-ing the two
existing group names instead of introducing a third permission system.
"""

from functools import wraps

from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.urls import reverse

from auditors.permissions import AUDITOR_GROUP_NAME
from common.roles import has_role
from officials.permissions import OFFICIAL_GROUP_NAME


def can_publish_results(user) -> bool:
    """True for an authenticated, is_staff user holding EITHER the
    Official or the Auditor group -- not a new role, just the existing
    two combined with OR, exactly as common/roles.py's docstring
    anticipates."""
    return has_role(user, OFFICIAL_GROUP_NAME) or has_role(user, AUDITOR_GROUP_NAME)


def publisher_required(view_func):
    """
    Same two-outcome shape as common.roles.role_required (not reused
    directly since that factory checks exactly one group name; this
    checks two with OR), to stay behaviourally consistent with
    official_required/auditor_required elsewhere in the codebase:
      - not authenticated at all -> redirected to the admin login.
      - authenticated, is_staff, but neither role -> 403 Forbidden.
      - Official or Auditor (or both) -> proceeds.
    """

    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path(), login_url=reverse("admin:login"))
        if not can_publish_results(request.user):
            raise PermissionDenied(
                "Publishing election results is restricted to election "
                "officials or compliance auditors."
            )
        return view_func(request, *args, **kwargs)

    return _wrapped
