"""
Auditor Dashboard access control -- the auditor-side half of
FR-OFF/AUD-01.

Same pattern as officials/permissions.py: the "Auditor" Role is a
Django Group, checked against `request.user` (django.contrib.auth) --
never against voter_sessions.Session or anything in the anonymous
Voter/OTP login flow (guardrail #3). The actual is_authenticated-and-
is_staff-and-group-membership logic lives once, shared, in
common/roles.py (has_role()/role_required()) -- this module is a thin,
Auditor-specific wrapper around it, exactly like officials/permissions.py
is for "Official". Neither app imports the other; both import
common.roles.

An account can hold both the "Official" and "Auditor" groups at once --
is_auditor()/auditor_required check only the "Auditor" group, so an
Official-only account (no "Auditor" membership) is correctly rejected
from this dashboard, and an account holding both is correctly admitted
to both dashboards independently.
"""

from common.roles import has_role, role_required

AUDITOR_GROUP_NAME = "Auditor"


def is_auditor(user) -> bool:
    """True only for an authenticated, is_staff Django user who also
    belongs to the "Auditor" group. See common/roles.has_role()."""
    return has_role(user, AUDITOR_GROUP_NAME)


auditor_required = role_required(
    AUDITOR_GROUP_NAME,
    "This dashboard is restricted to compliance auditors.",
)
