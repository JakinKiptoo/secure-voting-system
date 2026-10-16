"""
Officials Dashboard (FR-OFF-02 to FR-OFF-04; access control is the
officials-side half of FR-OFF/AUD-01, see officials/permissions.py).

Thread D, Part B restructures Part 1's single dashboard page into a
three-view sidebar shell (FRONTEND_STYLE.md's "Dashboard shell"
pattern):

  - overview_view   -- the single most relevant election (same
                        "currently active, else most recently closed"
                        selection Part 1 used), restyled as a
                        stat-card row. Selection logic is UNCHANGED
                        from Part 1, only its presentation moved/
                        restyled -- see _select_overview_election().
  - elections_view  -- NEW: every Election row regardless of status
                        (DRAFT/OPEN/CLOSED), filterable by status and
                        paginated, each row carrying its own Open/
                        Close quick-link forms. This is what actually
                        fixes the visibility gap: a DRAFT election
                        with no open/closed election elsewhere was
                        invisible on Part 1's single-election
                        dashboard; every election is findable here
                        the moment it's created.
  - candidates_view -- the existing FR-OFF-03 read-only candidate/
                        position list, now with an election selector
                        (GET param) so any election's candidates are
                        reachable, not just the Overview election.

Deliberately read-only and aggregate-only throughout, per guardrail
#1/#2 and FR-A-05's "no per-voter or per-ballot detail, even in an
internal admin UI" rule: every value put into any of these three
views' context is either a count, a status/label string, a formatted
time difference, or one of Election's/Candidate's own already-public
fields (title/dates/status, name/party/biography -- published
campaign information, not voter data). No Voter, Session, or Ballot
model INSTANCE is ever placed in the context -- only
Ballot.objects.count() and Voter.objects.count() integers.
officials/tests.py's leak tests check this directly for both the
Overview and the new Elections view, not just that each page renders.

Assumes at most one Election is OPEN at a time, same assumption
ballots/views.py already makes (not enforced anywhere at the model
level) -- consistent with the rest of the codebase. The new Elections
view does NOT depend on that assumption (it lists every election
whatever its status), but Overview's single-election selection still
does, exactly as in Part 1.
"""

from datetime import timedelta

from django.core.paginator import Paginator
from django.shortcuts import redirect, render
from django.utils import timezone

from ballots.models import Ballot
from elections.models import Candidate, Election
from voters.models import Voter

from .permissions import official_required

PAGE_SIZE = 25


def _format_timedelta(delta: timedelta) -> str:
    """
    Plain "Xd Yh Zm" rendering. No FR/NFR mandates a specific format;
    this is a reasonable proof-of-concept default, not a precision
    requirement.
    """
    total_seconds = max(int(delta.total_seconds()), 0)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, _ = divmod(remainder, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")
    return " ".join(parts)


def _select_overview_election():
    """
    Part 1's election-selection logic, moved out of the view body
    unchanged so Overview and (for its default) Candidates can share
    it, but NOT altered in substance: prefer the currently OPEN
    election; if none is open, fall back to the most recently CLOSED
    one (ordered by end_date, the closest proxy available since
    Election has no closed_at timestamp). Returns
    (election_or_none, is_showing_closed).
    """
    current_election = Election.objects.filter(status=Election.Status.OPEN).first()
    is_showing_closed = False

    if current_election is None:
        current_election = (
            Election.objects.filter(status=Election.Status.CLOSED)
            .order_by("-end_date")
            .first()
        )
        is_showing_closed = current_election is not None

    return current_election, is_showing_closed


@official_required
def dashboard_redirect_view(request):
    """
    Thread D, Part B: the old single "dashboard/" URL from Part 1 is
    kept as a redirect to the new Overview view, so any existing
    bookmark/link still lands somewhere sensible instead of 404ing.
    """
    return redirect("officials:overview")


@official_required
def overview_view(request):
    """
    Overview: Part 1's dashboard content (status/turnout/candidates/
    quick-links for the single most relevant election), restyled as a
    stat-card row per FRONTEND_STYLE.md, inside the new sidebar shell.
    The election-selection logic itself is untouched -- see
    _select_overview_election() above, which is Part 1's original
    `dashboard_view` body with no behavioural change.
    """
    context = {
        "active_nav": "overview",
        "no_election_exists": not Election.objects.exists(),
    }

    current_election, is_showing_closed = _select_overview_election()
    context["election"] = current_election
    context["is_showing_closed"] = is_showing_closed

    if current_election is not None:
        now = timezone.now()

        if current_election.status == Election.Status.OPEN:
            remaining = current_election.end_date - now
            if remaining.total_seconds() > 0:
                context["time_label"] = "Time remaining in voting window"
                context["time_display"] = _format_timedelta(remaining)
            else:
                # Past its scheduled end but an official hasn't
                # closed it yet -- FR-A-03's close is a deliberate
                # admin action, not a cron job, so this state is
                # expected and must render sensibly rather than
                # showing a negative duration.
                context["time_label"] = "Voting window elapsed"
                context["time_display"] = (
                    f"{_format_timedelta(-remaining)} overdue -- not yet closed"
                )
        else:  # CLOSED
            context["time_label"] = "Time since voting closed"
            context["time_display"] = _format_timedelta(now - current_election.end_date)

        # Turnout: cast-ballots / total-registered-voters, nothing
        # else. No "ballots issued" concept exists or is invented here
        # -- a Ballot row only ever exists once a vote has actually
        # been cast (created inside ballots/services.py:cast_ballot,
        # FR-V-04), so Ballot.objects.filter(election=X).count() IS
        # "ballots cast", not a proxy for it.
        ballot_count = Ballot.objects.filter(election=current_election).count()
        voter_count = Voter.objects.count()
        context["ballot_count"] = ballot_count
        context["voter_count"] = voter_count
        context["turnout_percent"] = (
            round((ballot_count / voter_count) * 100, 1) if voter_count > 0 else None
        )
        context["candidate_count"] = current_election.candidates.count()

    return render(request, "officials/overview.html", context)


@official_required
def elections_view(request):
    """
    Elections (NEW, Thread D Part B): every Election row regardless of
    status, filterable by status and paginated -- FRONTEND_STYLE.md's
    filterable/paginated table pattern, already used for
    auditors/views.py::audit_log_list_view and adapted here the same
    way.

    This is what resolves the visibility gap Part 1 left: a DRAFT
    election with no OPEN/CLOSED election elsewhere never appeared on
    Part 1's single-election dashboard. Every election a staff user
    creates is listed here the moment it exists, however it is sorted
    or filtered.

    Each row carries its own Open voting/Close voting quick-link
    forms -- the exact same mechanism Part 1's FR-OFF-04 already used
    (POST straight to the real, already-registered
    admin:elections_election_changelist action), just one pair per
    row instead of only for the single Overview election. No new
    open_voting()/close_voting() call path is introduced.

    Only Election's own fields are ever selected/rendered here (title,
    dates, status) plus a plain integer candidate count -- never a
    Voter, Session, or Ballot instance, and never a per-candidate vote
    count (Sprint 4 territory, unchanged scope).
    """
    elections = Election.objects.order_by("-start_date")

    status_filter = request.GET.get("status", "").strip().upper()
    if status_filter in Election.Status.values:
        elections = elections.filter(status=status_filter)

    paginator = Paginator(elections, PAGE_SIZE)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    return render(
        request,
        "officials/elections.html",
        {
            "active_nav": "elections",
            "page_obj": page_obj,
            "selected_status": status_filter,
            "status_choices": Election.Status.choices,
        },
    )


@official_required
def candidates_view(request):
    """
    Candidates (FR-OFF-03, moved from Part 1's single page): read-only
    candidate/position list for ONE election at a time, chosen via an
    `?election=<uuid>` GET param (an election selector dropdown in the
    template) rather than being locked to the single Overview
    election -- now that the Elections view exposes every election,
    Candidates needs to be reachable for any of them, not just
    whichever one Overview happens to be showing.

    Defaults to the same election Overview would show
    (_select_overview_election()) when no `?election=` param is given,
    so a plain click into "Candidates" from the sidebar still lands
    somewhere sensible rather than on an empty selector.

    Still deliberately .values()-only (plain dicts of already-public
    fields), not Candidate instances, and still no vote-count-per-
    candidate field -- that's a results/tally concern, out of scope
    here, unchanged from Part 1.
    """
    all_elections = list(Election.objects.order_by("-start_date"))

    selected_id = request.GET.get("election", "").strip()
    selected_election = None

    if selected_id:
        for election in all_elections:
            if str(election.election_id) == selected_id:
                selected_election = election
                break
    else:
        selected_election, _ = _select_overview_election()

    candidates = []
    if selected_election is not None:
        candidates = list(
            Candidate.objects.filter(election=selected_election)
            .order_by("name")
            .values("name", "party", "biography")
        )

    return render(
        request,
        "officials/candidates.html",
        {
            "active_nav": "candidates",
            "elections": all_elections,
            "selected_election": selected_election,
            "candidates": candidates,
        },
    )
