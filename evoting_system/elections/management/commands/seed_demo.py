"""
seed_demo -- create a clean, repeatable demo dataset (DEMO TOOLING ONLY).

Uses only the application's own public paths so every invariant holds:
  * staff accounts via User.objects.create_user + group membership
    (is_staff=True, group "Official"/"Auditor" -- same as a real account);
  * candidates are created while the election is DRAFT, then
    Election.open_voting() (FR-A-03/FR-A-04 respected, no bypass);
  * every ballot is cast through ballots.services.cast_ballot with a real
    Session from voter_sessions.services.issue_session, so the audit-log
    hash chain, participation rows and session deactivation are genuine;
  * the closed election is published with tally.services.publish_results.
It never edits grants, constraints, models or permissions, and it only
INSERTs into the audit log (so it runs fine as the restricted app role too).

Scenarios (an election cannot go back from OPEN to DRAFT, so the choice is
made when seeding):
  single   (default)  A open (+ B and C left DRAFT, to be opened live by an
                      Official), closed+published election. Voter Two has
                      voted in A. One open election => no chooser.
  chooser             B and C OPEN (FR-EL-06 chooser appears), no A,
                      closed+published election. Voter Two has voted in B.
"""

import random
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ballots.services import cast_ballot
from elections.models import Candidate, Election
from tally.services import publish_results
from voter_sessions.services import issue_session
from voters.crypto_utils import sha256_hex
from voters.models import Voter

from . import _demo_common as c


class Command(BaseCommand):
    help = "Create demo data (elections, staff accounts, voters). See DEMO_RUNBOOK.md."

    def add_arguments(self, parser):
        parser.add_argument("--scenario", choices=["single", "chooser"], default="single")
        parser.add_argument("--password", default=c.DEFAULT_DEMO_PASSWORD,
                            help="Password for the demo staff accounts (demo use only).")
        parser.add_argument("--with-admin", action="store_true",
                            help="Also create a demo SUPERUSER (needed to show FR-A-01..04 in the Django admin).")

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        if not settings.DEBUG:
            raise CommandError("Refusing to seed demo data while DEBUG is off (looks like a non-demo environment).")
        if (Election.objects.filter(title__startswith=c.DEMO_PREFIX).exists()
                or User.objects.filter(username__in=c.STAFF_USERNAMES).exists()
                or Voter.objects.filter(national_id_hash__in=[sha256_hex(n) for n in c.ALL_DEMO_NATIONAL_IDS]).exists()):
            raise CommandError("Demo data already present. Run `python manage.py reset_demo --yes` first.")

        scenario = opts["scenario"]
        self._make_staff(opts["password"], opts["with_admin"])
        voters = self._make_voters()

        closed = self._make_closed_published(voters)
        if scenario == "single":
            open_a = self._election(c.TITLE_OPEN_A, ["Wanjiku Mwangi|Unity Party", "Peter Kamau|Progress Alliance", "Fatuma Hassan|Independent"], open_now=True)
            self._election(c.TITLE_OPEN_B, ["Otieno Odhiambo|Hostel Union", "Mercy Chebet|Independent"], open_now=False)
            self._election(c.TITLE_OPEN_C, ["Kevin Mutua|Sports Club", "Lilian Njeri|Independent"], open_now=False)
            voted_in = open_a
        else:
            b = self._election(c.TITLE_OPEN_B, ["Otieno Odhiambo|Hostel Union", "Mercy Chebet|Independent"], open_now=True)
            self._election(c.TITLE_OPEN_C, ["Kevin Mutua|Sports Club", "Lilian Njeri|Independent"], open_now=True)
            voted_in = b

        # Voter Two "already voted": through the real casting service.
        self._cast(voters["two"], voted_in.candidates.order_by("name").first())

        self.stdout.write(self.style.SUCCESS(f"Demo data created (scenario: {scenario})."))
        self.stdout.write(f"  Official : {c.OFFICIAL_USERNAME}   Auditor: {c.AUDITOR_USERNAME}"
                          + (f"   Admin: {c.ADMIN_USERNAME}" if opts["with_admin"] else ""))
        self.stdout.write("  Password : (the demo password; default is printed in DEMO_RUNBOOK.md)")
        self.stdout.write(f"  Voter 1 (NOT voted): National ID {c.VOTER_ONE[0]}  phone {c.VOTER_ONE[2]}")
        self.stdout.write(f"  Voter 2 (HAS voted): National ID {c.VOTER_TWO[0]}  phone {c.VOTER_TWO[2]}")
        self.stdout.write(f"  Closed+published   : {closed.title}")

    # ------------------------------------------------------------------
    def _make_staff(self, password, with_admin):
        auditor_group, _ = Group.objects.get_or_create(name="Auditor")   # no migration creates this one
        official_group, _ = Group.objects.get_or_create(name="Official")  # already made by officials/0001
        for username, group in ((c.OFFICIAL_USERNAME, official_group), (c.AUDITOR_USERNAME, auditor_group)):
            user = User.objects.create_user(username=username, password=password, is_staff=True)
            user.groups.add(group)
        if with_admin:
            User.objects.create_superuser(username=c.ADMIN_USERNAME, password=password, email="")

    def _make_voters(self):
        def mk(t):
            return Voter.objects.create(national_id_hash=sha256_hex(t[0]), full_name=t[1], phone_number=t[2])
        return {"one": mk(c.VOTER_ONE), "two": mk(c.VOTER_TWO), "background": [mk(t) for t in c.BACKGROUND_VOTERS]}

    def _election(self, title, candidates, open_now, past=False):
        now = timezone.now()
        start, end = (now - timedelta(days=30), now - timedelta(days=29)) if past else (now - timedelta(hours=1), now + timedelta(days=7))
        election = Election.objects.create(title=title, start_date=start, end_date=end)
        for entry in candidates:                       # FR-A-04: candidates while DRAFT
            name, party = entry.split("|")
            Candidate.objects.create(election=election, name=name, party=party,
                                     biography=f"Demo candidate for {title}.")
        if open_now:
            election.open_voting()                     # FR-A-03
        return election

    def _cast(self, voter, candidate):
        session = issue_session(voter)
        return cast_ballot(str(session.uuid_token), candidate.candidate_id)

    def _make_closed_published(self, voters):
        election = self._election(
            c.TITLE_CLOSED,
            ["Grace Akinyi|Readers Party", "Daniel Kiprop|Campus Forward", "Halima Ali|Independent"],
            open_now=True, past=True,
        )
        cands = list(election.candidates.order_by("name"))
        rng = random.Random(2026)                      # deterministic tally for the demo
        weights = [0.5, 0.3, 0.2]
        for voter in voters["background"]:
            self._cast(voter, rng.choices(cands, weights=weights)[0])
        election.close_voting()                        # FR-A-03
        publish_results(election)                      # FR-EL-03 / FR-P-02
        return election
