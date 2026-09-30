"""
Session Management Module service functions.

Sprint 2 scope: token issuance only (FR-S-01), on successful MFA.
Token destruction (FR-V-05) is Sprint 3's ballot-casting transaction
and is NOT implemented here.
"""

from datetime import timedelta

from django.utils import timezone

from voters.models import Voter

from .models import Session

# Not specified by any FR/NFR -- a reasonable proof-of-concept default
# for how long an authenticated-but-not-yet-voted session stays valid.
# Revisit if Sprint 3/5 needs a different figure.
SESSION_TOKEN_LIFETIME_MINUTES = 15


def issue_session(voter: Voter) -> Session:
    """
    Issue a single-use, session-bound UUID token for `voter` on
    successful MFA (FR-S-01).

    Does not check for or invalidate any prior active Session for
    this voter -- see voters/views.py docstring / Sprint 2 handover
    for why that's out of scope here and left as a Sprint 3
    consideration.
    """
    return Session.objects.create(
        voter=voter,
        expiry_time=timezone.now() + timedelta(minutes=SESSION_TOKEN_LIFETIME_MINUTES),
        is_active=True,
    )
