"""
FR-EL-05: one-time backfill of VoterElectionParticipation for any
Voter row that already has has_voted=True from before this feature
existed (i.e. from the single-global-boolean era).

Why this is needed at all: Voter.has_voted=True on its own doesn't say
WHICH Election that vote was cast in -- the information this feature
needs to scope by -- and Ballot carries no FK back to Voter (the
anonymisation invariant, SCHEMA.md), so there is no direct join to
recover it from. This uses the same kind of timing-proximity inference
the FR-EL-05 prompt itself anticipated ("inferred from Ballot
timestamps if needed"), over the following resolution order per
has_voted=True voter with no existing participation row:

  1. Exactly one Election exists at all -> unambiguous, use it.
  2. More than one Election exists -> pick whichever Election's
     start_date is nearest the voter's registration_date, as the best
     available proxy without a Voter->Ballot link. This is a
     heuristic, not a guarantee of correctness for a real multi-
     election, multi-voter dataset -- flagged explicitly in the
     FR-EL-05 handover, not hidden. It is adequate for this project's
     proof-of-concept dev data (verified against the actual dev DB
     before writing this: exactly one pre-existing has_voted=True
     Voter, one Election, one Ballot -- case 1 above, unambiguous).
  3. No Election exists at all -> nothing to backfill against; logged
     and left unresolved rather than guessed.

voted_at is populated from the nearest Ballot's created_at within the
chosen Election when one exists (the closest available proxy for "when
this voter voted", again without ever reading a Voter<->Ballot join
that doesn't exist), falling back to the voter's registration_date
otherwise.

Idempotent / re-run safe: skips any voter that already has a
participation row (so re-running `migrate` after a partial run, or a
fake-then-real replay, never double-inserts).
"""

from django.db import migrations


def backfill_participation(apps, schema_editor):
    Voter = apps.get_model("voters", "Voter")
    Election = apps.get_model("elections", "Election")
    VoterElectionParticipation = apps.get_model("voters", "VoterElectionParticipation")
    Ballot = apps.get_model("ballots", "Ballot")

    unresolved_voter_ids = []

    for voter in Voter.objects.filter(has_voted=True):
        if VoterElectionParticipation.objects.filter(voter=voter).exists():
            continue  # already backfilled (or genuinely voted post-feature)

        elections = list(Election.objects.all())
        if len(elections) == 1:
            target_election = elections[0]
        elif len(elections) == 0:
            unresolved_voter_ids.append(str(voter.voter_id))
            continue
        else:
            target_election = min(
                elections,
                key=lambda e: abs((e.start_date - voter.registration_date).total_seconds()),
            )

        nearest_ballot = (
            Ballot.objects.filter(election=target_election).order_by("created_at").first()
        )
        voted_at = nearest_ballot.created_at if nearest_ballot else voter.registration_date

        VoterElectionParticipation.objects.create(
            voter=voter,
            election=target_election,
            has_voted=True,
            voted_at=voted_at,
        )

    if unresolved_voter_ids:
        # Not raised as an error -- a migration failing outright over
        # historical data would block `migrate` entirely. Printed so
        # it's impossible to miss in migration output; also exactly
        # what to check for in a fresh handover/review.
        print(
            "\n"
            "WARNING (FR-EL-05 backfill): could not backfill "
            "VoterElectionParticipation for has_voted=True voter(s) "
            f"with no Election row to attribute them to: {unresolved_voter_ids}. "
            "These voters will still be treated as globally "
            "has_voted=True (display only) but have no per-election "
            "participation row -- investigate manually if this matters."
        )


def noop_reverse(apps, schema_editor):
    # Deliberately not reversible: there is no way to tell, on a
    # reverse migration, which VoterElectionParticipation rows were
    # created by this backfill versus by normal cast_ballot() usage
    # since -- so reversing does nothing rather than guessing which
    # rows to delete.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("voters", "0003_alter_voter_has_voted_voterelectionparticipation"),
        ("ballots", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(backfill_participation, noop_reverse),
    ]
