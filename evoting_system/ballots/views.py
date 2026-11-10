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

from elections.models import Election
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY

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


def cast_ballot_view(request):
    token = request.session.get(VOTING_TOKEN_SESSION_KEY)
    if not token:
        return render(
            request,
            "ballots/cast_rejected.html",
            {"reason": "You need to log in before casting a ballot."},
        )

    open_elections = list(Election.objects.filter(status=Election.Status.OPEN).order_by("title"))

    if len(open_elections) <= 1:
        # Unchanged common-case behavior: zero -> "no election open"
        # (cast.html's existing {% else %} branch); exactly one -> use
        # it directly, no chooser step shown.
        election = open_elections[0] if open_elections else None
    else:
        election = _resolve_requested_election(request, open_elections)
        if election is None:
            return render(request, "ballots/choose_election.html", {"elections": open_elections})

    if request.method == "POST":
        form = BallotForm(request.POST, election=election)
        if form.is_valid():
            try:
                result = cast_ballot(
                    uuid_token=token,
                    candidate_id=form.cleaned_data["candidate"].candidate_id,
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
            request.session.pop(VOTING_TOKEN_SESSION_KEY, None)

            return render(
                request,
                "ballots/confirmation.html",
                {
                    "ballot_id": result.ballot.ballot_id,
                    "audit_hash": result.audit_entry.ballot_hash,
                },
            )
    else:
        form = BallotForm(election=election)

    return render(
        request,
        "ballots/cast.html",
        {"form": form, "election": election},
    )