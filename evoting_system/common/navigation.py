"""
FR-NAV-01 (EXTENSIONS_ROADMAP.md): shared, role-aware site navigation.

DISPLAY ONLY. This context processor decides which links to *show*; it
grants nothing. Every protected page still enforces its own access
control server-side exactly as before (common.roles.role_required,
tally.permissions.publisher_required, the voting-token checks), and no
URL or role check is changed here. The visibility rules deliberately
reuse common.roles.has_role -- the same predicate the pages themselves
use -- so a link is shown only to someone who would actually be let in.

Context contract: `site_nav` is a plain dict of strings/booleans only
(no model instances, no tokens, no ids), so it can never leak
voter/session/ballot data into any template context (FR-P-03 style
leak tests walk every context value).

Who sees what:
  Anonymous            Home, Public results, Privacy, Voter login, Staff login
  Official             Overview, Elections, Candidates, Public results, Logout
  Auditor              Audit log, Verify chain, Compliance, Public results, Logout
  Both roles           both role groups above (Logout once)
  Staff, no role       Home, Administration, Public results, Logout
  Voter mid-flow       Ballot, End session  (a voting token is held in the
                       browser session; no staff roles)
A browser can hold a staff login and a voting token at once; the two
sets of links then simply combine.
"""

from django.urls import reverse

from voter_sessions.services import VOTING_TOKEN_SESSION_KEY

from .roles import has_role

# Plain strings, same as common/staff_login_redirect.py (importing from
# officials/auditors here would be circular for the same reason).
OFFICIAL_GROUP_NAME = "Official"
AUDITOR_GROUP_NAME = "Auditor"


def _link(request, label, url_name):
    url = reverse(url_name)
    return {"label": label, "url": url, "active": request.path == url}


def site_navigation(request):
    user = getattr(request, "user", None)
    is_staff_user = bool(user is not None and user.is_authenticated and user.is_staff)
    is_official = is_staff_user and has_role(user, OFFICIAL_GROUP_NAME)
    is_auditor = is_staff_user and has_role(user, AUDITOR_GROUP_NAME)

    session = getattr(request, "session", None)
    voter_mid_flow = bool(session is not None and session.get(VOTING_TOKEN_SESSION_KEY))

    links = []
    if is_official:
        links += [
            _link(request, "Overview", "officials:overview"),
            _link(request, "Elections", "officials:elections"),
            _link(request, "Candidates", "officials:candidates"),
        ]
    if is_auditor:
        links += [
            _link(request, "Audit log", "auditors:audit_log_list"),
            _link(request, "Verify chain", "auditors:verify_chain"),
            _link(request, "Compliance", "auditors:dpa_checklist"),
        ]
    if is_staff_user and not (is_official or is_auditor):
        links += [
            _link(request, "Home", "home"),
            _link(request, "Administration", "admin:index"),
        ]
    if voter_mid_flow:
        links.append(_link(request, "Ballot", "ballots:cast"))

    if is_staff_user or voter_mid_flow:
        links.append(_link(request, "Public results", "tally:index"))
    else:
        links += [
            _link(request, "Home", "home"),
            _link(request, "Public results", "tally:index"),
            _link(request, "Privacy", "voters:privacy"),
            _link(request, "Voter login", "voters:credentials"),
            _link(request, "Staff login", "admin:login"),
        ]

    return {
        "site_nav": {
            "links": links,
            "show_logout": is_staff_user,
            "logout_url": reverse("staff_logout"),
            "show_end_session": voter_mid_flow,
            "end_session_url": reverse("voters:end_session"),
        }
    }
