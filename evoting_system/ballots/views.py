"""
Ballot Casting Module view.

Proof-of-concept scope: assumes at most one Election is OPEN at a
time (not enforced anywhere -- if an admin opens two, this view just
uses the first one returned). No FR/NFR requires multi-election
concurrency, and REQUIREMENTS.md doesn't describe how a voter would
choose between simultaneously open elections, so this is a flagged
simplification, not an attempt at that.
"""

from django.shortcuts import render

from elections.models import Election
from voter_sessions.services import VOTING_TOKEN_SESSION_KEY

from .forms import BallotForm
from .services import BallotCastError, cast_ballot


def cast_ballot_view(request):
    token = request.session.get(VOTING_TOKEN_SESSION_KEY)
    if not token:
        return render(
            request,
            "ballots/cast_rejected.html",
            {"reason": "You need to log in before casting a ballot."},
        )

    election = Election.objects.filter(status=Election.Status.OPEN).first()

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
