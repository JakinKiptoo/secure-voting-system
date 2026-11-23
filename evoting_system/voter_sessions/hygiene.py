"""
Session hygiene helpers: FR-SES-01 to FR-SES-03 (EXTENSIONS_ROADMAP.md).

Kept in their own module, NOT in services.py::issue_session, on purpose:
existing tests call issue_session twice to create two active sessions,
so issue_session's behaviour must not change. These helpers are called
from the view layer (voters/views.py at OTP success and for "End
session", ballots/views.py before a voting token is used).

Nothing here touches cast_ballot, its transaction, the audit chain or
any Ballot/anonymity code, and nothing here ever *creates* a link
between a session and a ballot. It only flips Session.is_active to
False (the same "deactivate, don't delete" approach cast_ballot uses
for FR-V-05) and removes keys from the browser session.
"""

import uuid
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone

from .models import Session
from .services import VOTING_TOKEN_SESSION_KEY

# Browser-session key holding when OTP verification succeeded (ISO 8601).
AUTHENTICATED_AT_SESSION_KEY = "voter_authenticated_at"

DEFAULT_ABSOLUTE_TIMEOUT_MINUTES = 30


def absolute_timeout() -> timedelta:
    minutes = getattr(
        settings, "VOTER_SESSION_ABSOLUTE_TIMEOUT_MINUTES", DEFAULT_ABSOLUTE_TIMEOUT_MINUTES
    )
    return timedelta(minutes=minutes)


def mark_authenticated(request) -> None:
    """FR-SES-02: record the moment OTP verification succeeded."""
    request.session[AUTHENTICATED_AT_SESSION_KEY] = timezone.now().isoformat()


def deactivate_other_sessions(voter, keep_session) -> int:
    """FR-SES-01: deactivate every OTHER active Session of this voter
    (only `keep_session`, the one just issued, stays active). Returns
    the number of rows deactivated."""
    return (
        Session.objects.filter(voter=voter, is_active=True)
        .exclude(pk=keep_session.pk)
        .update(is_active=False)
    )


def _deactivate_token(token) -> None:
    try:
        token_uuid = uuid.UUID(str(token))
    except (ValueError, AttributeError, TypeError):
        return  # not a valid token string: nothing to deactivate
    Session.objects.filter(uuid_token=token_uuid, is_active=True).update(is_active=False)


def clear_voting_keys(request) -> None:
    """Remove the voting token and its authentication timestamp from the
    browser session."""
    request.session.pop(VOTING_TOKEN_SESSION_KEY, None)
    request.session.pop(AUTHENTICATED_AT_SESSION_KEY, None)


def end_current_session(request) -> bool:
    """FR-SES-03: deactivate the current Session row and clear the voting
    keys. Returns True if a voting token was present. Safe to call with
    no token (does nothing)."""
    token = request.session.get(VOTING_TOKEN_SESSION_KEY)
    if token:
        _deactivate_token(token)
    clear_voting_keys(request)
    return bool(token)


def absolute_timeout_exceeded(request) -> bool:
    """FR-SES-02: True if more than the configured maximum has passed
    since OTP success. A browser session with no authenticated_at (one
    that predates this feature, or a test that sets the token directly)
    is not treated as expired here; the Session row's own expiry_time
    (15 minutes, FR-S-01) still applies inside cast_ballot."""
    raw = request.session.get(AUTHENTICATED_AT_SESSION_KEY)
    if not raw:
        return False
    try:
        authenticated_at = datetime.fromisoformat(raw)
    except ValueError:
        return True  # unreadable timestamp: fail closed
    return timezone.now() - authenticated_at > absolute_timeout()


def expire_if_timed_out(request) -> bool:
    """FR-SES-02: if the absolute timeout has passed, deactivate the
    token, clear the voting keys and return True (caller shows the
    "session expired" page). Otherwise return False and change nothing."""
    if not request.session.get(VOTING_TOKEN_SESSION_KEY):
        return False
    if not absolute_timeout_exceeded(request):
        return False
    end_current_session(request)
    return True
