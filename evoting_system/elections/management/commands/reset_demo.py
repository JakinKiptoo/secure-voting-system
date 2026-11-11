"""
reset_demo -- remove everything seed_demo created (DEMO TOOLING ONLY).

Does NOT change any grant, constraint or permission. The audit log is
insert-only for the restricted application role by design, so deleting
demo audit rows needs the database OWNER role (the one in DB_USER, e.g.
evoting_user), which is what `manage.py` uses by default. If this command
is run as the restricted role it fails with "permission denied" and says
so -- that failure is the FR-DB-01 control working, not a bug.

Safety: refuses unless DEBUG is on, requires --yes, and refuses if the
audit log holds any row that is not a demo ballot (so it can never silently
break a real chain). For a non-demo database, drop and recreate it instead.
"""

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import ProgrammingError, transaction
from django.db.utils import InternalError

from auditlog.models import AuditLog
from ballots.models import Ballot
from elections.models import Candidate, Election
from tally.models import ElectionResult
from voter_sessions.models import Session
from voters.crypto_utils import sha256_hex
from voters.models import Voter, VoterElectionParticipation

from . import _demo_common as c


class Command(BaseCommand):
    help = "Delete all demo data created by seed_demo (needs --yes)."

    def add_arguments(self, parser):
        parser.add_argument("--yes", action="store_true", help="Confirm deletion.")

    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Refusing to reset while DEBUG is off.")
        if not opts["yes"]:
            raise CommandError("Add --yes to confirm deleting demo data.")

        elections = Election.objects.filter(title__startswith=c.DEMO_PREFIX)
        ballots = Ballot.objects.filter(election__in=elections)
        stray = AuditLog.objects.exclude(ballot__in=ballots).count()
        if stray:
            raise CommandError(
                f"{stray} audit-log row(s) belong to non-demo ballots. Not resetting: "
                "this is not a pure demo database. Drop and recreate the DB instead."
            )
        voter_hashes = [sha256_hex(n) for n in c.ALL_DEMO_NATIONAL_IDS]
        voters = Voter.objects.filter(national_id_hash__in=voter_hashes)

        try:
            with transaction.atomic():
                n_audit = AuditLog.objects.filter(ballot__in=ballots).delete()[0]
                n_ballots = ballots.delete()[0]
                ElectionResult.objects.filter(election__in=elections).delete()
                VoterElectionParticipation.objects.filter(election__in=elections).delete()
                VoterElectionParticipation.objects.filter(voter__in=voters).delete()
                Session.objects.filter(voter__in=voters).delete()
                n_voters = voters.delete()[0]
                Candidate.objects.filter(election__in=elections).delete()
                n_elections = elections.delete()[0]
                n_users = User.objects.filter(username__in=c.STAFF_USERNAMES).delete()[0]
        except (ProgrammingError, InternalError) as exc:
            if "permission denied" in str(exc).lower():
                raise CommandError(
                    "permission denied deleting audit-log rows: you are connected as the restricted "
                    "application role (FR-DB-01 working as designed). Re-run reset_demo with the owner "
                    "role credentials (DB_USER in .env), not evoting_app."
                ) from exc
            raise

        self.stdout.write(self.style.SUCCESS(
            f"Demo data removed (audit rows {n_audit}, ballots {n_ballots}, elections/candidates {n_elections}, "
            f"voters/sessions {n_voters}, staff users {n_users} row-deletions incl. cascades)."))
