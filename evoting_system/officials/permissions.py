"""
Officials Dashboard access control -- the officials-side half of
FR-OFF/AUD-01.

FR-OFF-01's Role concept is implemented as a Django Group named
"Official", checked against `request.user` (django.contrib.auth) --
NOT against voter_sessions.Session or anything in the anonymous
Voter/OTP login flow. A Group was chosen over a new profile model
because it needs zero new tables and reuses Django's existing
RBAC machinery (the same User/Group/Permission tables already backing
Django admin), which keeps this role system from touching, importing,
or duplicating anything in voter_sessions (guardrail #3) -- there is
nothing here for it to touch, since officials/models.py defines no
model at all.

Thread A, Part 2 (Auditor Dashboard) note: the actual role-check logic
previously defined in this file now lives in common/roles.py as
has_role()/role_required(), shared with the new auditors/ app so the
same is_authenticated-and-is_staff-and-group-membership pattern isn't
duplicated a second time. is_official() and official_required below
are now thin, behaviourally-identical wrappers around that shared
helper -- kept here, under these same names, so officials/views.py
and officials/tests.py (Part 1, unmodified) don't need to change at
all. See common/roles.py for the full reasoning, including why
is_staff is required in addition to group membership.
"""

from common.roles import has_role, role_required

OFFICIAL_GROUP_NAME = "Official"


def is_official(user) -> bool:
    """True only for an authenticated, is_staff Django user who also
    belongs to the "Official" group. See common/roles.has_role()."""
    return has_role(user, OFFICIAL_GROUP_NAME)


official_required = role_required(
    OFFICIAL_GROUP_NAME,
    "This dashboard is restricted to election officials.",
)
