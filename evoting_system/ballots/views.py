"""
Ballot Casting Module view.

FR-EL-06 Phase 2 (EXTENSIONS_ROADMAP.md): resolves the gap Phase 1
(ballots/test_fr_el_06_investigation.py) only observed and did not
fix. That investigation confirmed two things: (1) nothing in the model
layer stops two Elections being OPEN at once, and (2) the view used to
pick whichever one `Election.objects.filter(status=OPEN).first()`
happened to return, with no way for the voter to choose.

Direction taken: give the voter an explicit choice, NOT a model-level
single-open-election guard. Checked against REQUIREMENTS.md and
CLAUDE.md first (see the FR-EL-06 handover for the full reasoning) --
neither states or structurally implies that only one Election may be
OPEN at a time; nothing in SCHEMA.md's Election entity or DIAGRAMS.md's
diagrams constrains OPEN-election cardinality either. Meanwhile
FR-OFF-04 (the officials Elections view, EXTENSIONS_ROADMAP.md) already
treats multiple simultaneous elections of any status, OPEN included, as
an ordinary, filterable, paginated list -- there is no "only one at a
time" assumption anywhere else in the system this would need to stay
consistent with. A guard at Election.open_voting() rejecting a second
OPEN election would therefore be inventing a new restriction the spec
never asked for, not enforcing an existing one.

So: when exactly zero or one Election is OPEN, behavior is byte-for-
byte unchanged from before (the common case is not touched). When MORE
THAN ONE Election is OPEN, the voter is shown an election-selection
step (ballots/choose_election.html) before the ballot form, and must
pick one via `?election=<uuid>` (GET, from the chooser's links) or a
hidden `election` field carried through the ballot form's own POST --
re-validated as still OPEN on every request, not trusted from a stale
link/tab. cast_ballot() itself needed no change: it already resolves
the election from the submitted candidate_id, never from an
independent "the open election" lookup of its own (Phase 1 already
proved this -- see that test file's final assertions).
"""

from django.shortcuts import render
from django.urls import reverse

from voter_sessions import hygiene
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session

from . import pending
from .forms import BallotForm
from .services import BallotCastError, cast_ballot


def _resolve_requested_election(request, open_elections):
    """
    FR-EL-06 Phase 2 helper: given the Elections that are OPEN *right
    now* (freshly queried by the caller on every request, never
    cached across GET/POST), find which one the voter actually
    selected -- from the `election` GET param (the chooser's own
    links) on a GET request, or the hidden `election` field carried
    inside the ballot form's POST body. Returns None if nothing valid
    was submitted (first visit to the chooser) or if the submitted id
    doesn't match any currently-OPEN election (stale tab, or the
    election closed between the chooser and the ballot submission) --
    the caller re-shows the chooser in either case, rather than ever
    guessing.
    """
    source = request.POST if request.method == "POST" else request.GET
    requested_id = source.get("election", "").strip()
    if not requested_id:
        return None
    for election in open_elections:
        if str(election.election_id) == requested_id:
            return election
    return None


def _election_url(election):
    return f"{reverse('ballots:cast')}?election={election.election_id}"


def _skip_url(current, pending_list):
    """FR-EL-07: where "Skip for now" goes -- the next pending ballot after
    the current one (wrapping round), or None if there is no other. Pure
    navigation: nothing is recorded."""
    others = [e for e in pending_list if e.election_id != current.election_id]
    if not others:
        return None
    later = [e for e in others if (e.start_date, e.title) > (current.start_date, current.title)]
    return _election_url((later or others)[0])


def _after_commit(request, voter, authenticated_at, timed_out):
    """FR-EL-07: runs only AFTER cast_ballot's transaction has committed
    and the confirmation is certain. Decides what the receipt page offers
    next and, for a continuation, mints a fresh single-use token for the
    same login (no new OTP) with the existing issue_session. Each ballot
    keeps its own token, destroyed in its own transaction by cast_ballot.
    Re-evaluates pending from scratch (an election that closed meanwhile
    is simply not pending)."""
    if voter is None:
        return {"all_done": True}
    entries = pending.checklist(voter, pending.open_elections_in_order())
    still_pending = pending.pending_elections(entries)
    if not still_pending:
        return {"all_done": True}
    if timed_out:
        return {"timed_out": True, "pending_count": len(still_pending)}
    fresh = issue_session(voter)
    request.session[VOTING_TOKEN_SESSION_KEY] = str(fresh.uuid_token)
    if authenticated_at:
        # The absolute timeout counts from the original OTP login, not from
        # each ballot: carry the original timestamp over, never reset it.
        request.session[hygiene.AUTHENTICATED_AT_SESSION_KEY] = authenticated_at
    return {
        "pending_count": len(still_pending),
        "next_election_title": still_pending[0].title,
        "next_election_url": _election_url(still_pending[0]),
    }


def cast_ballot_view(request):
    # FR-SES-02: absolute timeout since OTP success, enforced before the
    # voting token is used at all. cast_ballot itself is unchanged.
    if hygiene.expire_if_timed_out(request):
        return render(request, "voters/session_expired.html")

    token = request.session.get(VOTING_TOKEN_SESSION_KEY)
    if not token:
        return render(
            request,
            "ballots/cast_rejected.html",
            {"reason": "You need to log in before casting a ballot."},
        )

    # FR-EL-07: the voter's checklist, rebuilt on every request from
    # participation rows only (see ballots/pending.py).
    voter = pending.voter_for_token(token)
    open_elections = pending.open_elections_in_order()
    entries = pending.checklist(voter, open_elections)
    pending_list = pending.pending_elections(entries)

    if len(open_elections) <= 1:
        # Unchanged common-case behavior: zero -> "no election open"
        # (cast.html's existing {% else %} branch); exactly one -> use
        # it directly, no chooser step shown.
        election = open_elections[0] if open_elections else None
    else:
        election = _resolve_requested_election(request, pending_list)
        if election is None:
            return render(
                request,
                "ballots/choose_election.html",
                {"entries": entries, "pending_count": len(pending_list)},
            )

    if request.method == "POST":
        form = BallotForm(request.POST, election=election)
        if form.is_valid():
            try:
                result = cast_ballot(
                    uuid_token=token,
                    candidate_id=form.cleaned_data["candidate"].candidate_id,
                    expected_election_id=election.election_id,  # the election validated above
                )
            except BallotCastError as exc:
                return render(
                    request, "ballots/cast_rejected.html", {"reason": str(exc)}
                )

            # Sprint 2 carry-forward item: the ballot-casting
            # transaction (cast_ballot) just destroyed the domain
            # Session row this token pointed to. Explicitly clear the
            # matching request.session key here too, in this same
            # view, so Django's own session store doesn't keep
            # referencing a token that no longer exists anywhere.
            #
            # FR-EL-07: keep the original login time and check the absolute
            # timeout (FR-SES-02) once more, now that the ballot is committed.
            authenticated_at = request.session.get(hygiene.AUTHENTICATED_AT_SESSION_KEY)
            timed_out = hygiene.absolute_timeout_exceeded(request)
            hygiene.clear_voting_keys(request)  # removes the token (FR-V-05 browser side) and its timestamp

            context = {
                "ballot_id": result.ballot.ballot_id,
                "audit_hash": result.audit_entry.ballot_hash,
            }
            context.update(_after_commit(request, voter, authenticated_at, timed_out))
            return render(request, "ballots/confirmation.html", context)
    else:
        form = BallotForm(election=election)

    skip_url = _skip_url(election, pending_list) if election is not None and len(open_elections) > 1 else None
    return render(
        request,
        "ballots/cast.html",
        {"form": form, "election": election, "skip_url": skip_url},
    )