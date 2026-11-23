"""
FR-EL-07 (EXTENSIONS_ROADMAP.md): the "your ballots" checklist.

Scope is "cycle-lite": the cycle is simply the set of elections that are
OPEN *right now*. There is no ElectionCycle model and no schema change;
this module is read-only queries.

Pending ballots for a voter = currently OPEN elections in which that
voter has no VoterElectionParticipation row with has_voted = True,
ordered by (start_date, title). The checklist is built from
participation rows ONLY (voter, election, has_voted) -- the same
"poll-book" FR-EL-05 already keeps. It never reads Ballot, Candidate
choices or AuditLog, and it introduces no shared "ballot paper"
identifier: the only thing tying a voter's several ballots together is
the pre-existing fact that the same voter has several participation
rows, which says THAT they voted, never WHAT.

Everything is re-evaluated on every request (nothing cached): an
election that closes drops out, one that opens appears.
"""

import uuid

from django.core.exceptions import ValidationError
from django.utils import timezone

from elections.models import Election
from voter_sessions.models import Session
from voters.models import VoterElectionParticipation


def open_elections_in_order():
    """Currently OPEN elections, deterministic order (start_date, title)."""
    return list(Election.objects.filter(status=Election.Status.OPEN).order_by("start_date", "title"))


def voter_for_token(token):
    """The Voter behind a still-valid voting token, or None.

    Used only to look up the voter's participation rows. The result is
    never put in a template context and never stored anywhere."""
    try:
        token_uuid = uuid.UUID(str(token))
    except (ValueError, AttributeError, TypeError):
        return None
    try:
        session = (
            Session.objects.select_related("voter")
            .filter(uuid_token=token_uuid, is_active=True, expiry_time__gt=timezone.now())
            .first()
        )
    except ValidationError:
        return None
    return session.voter if session else None


def checklist(voter, open_elections):
    """[{"election": Election, "done": bool}, ...] in the given order.

    `voter` None (unknown/expired token) marks everything pending, which
    keeps the pre-FR-EL-07 behaviour: cast_ballot itself rejects a bad
    token or a repeat vote."""
    voted_ids = set()
    if voter is not None and open_elections:
        voted_ids = set(
            VoterElectionParticipation.objects.filter(
                voter=voter, has_voted=True, election__in=open_elections
            ).values_list("election_id", flat=True)
        )
    return [{"election": e, "done": e.election_id in voted_ids} for e in open_elections]


def pending_elections(entries):
    return [entry["election"] for entry in entries if not entry["done"]]
