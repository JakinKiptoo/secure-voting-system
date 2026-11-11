"""
Shared constants for the demo helpers (seed_demo / reset_demo).

DEMO TOOLING ONLY. Nothing here is imported by application code, and
nothing here changes any model, constraint, grant or permission. Every
demo row is recognisable by the "[DEMO]" title prefix (elections), the
"demo." username prefix (staff) or the fixed demo National IDs below
(voters), which is how reset_demo finds exactly what seed_demo made.
"""

DEMO_PREFIX = "[DEMO] "

# Demo-only credentials. These are published in DEMO_RUNBOOK.md on purpose;
# they exist only in a throwaway demo database. Override with --password.
DEFAULT_DEMO_PASSWORD = "DemoPass-2026!"

OFFICIAL_USERNAME = "demo.official"
AUDITOR_USERNAME = "demo.auditor"
ADMIN_USERNAME = "demo.admin"
STAFF_USERNAMES = (OFFICIAL_USERNAME, AUDITOR_USERNAME, ADMIN_USERNAME)

# (national_id, full_name, phone_number). The two "named" demo voters:
VOTER_ONE = ("39000001", "Amina Demo Wanjiru", "+254700000001")   # has NOT voted
VOTER_TWO = ("39000002", "Brian Demo Otieno", "+254700000002")    # HAS voted
# Background electorate whose ballots populate the CLOSED+PUBLISHED election
# so its tally and audit chain are non-trivial. Never used to log in.
BACKGROUND_VOTERS = [
    (f"3900010{i}", f"Demo Background Voter {i}", f"+25470000010{i}") for i in range(1, 7)
]
# Reserved for the live FR-V-00 registration step: the presenter registers
# this National ID on stage, and reset_demo removes it again.
LIVE_REGISTRATION = ("39000099", "Live Demo Registrant", "+254700000099")
ALL_DEMO_NATIONAL_IDS = (
    [VOTER_ONE[0], VOTER_TWO[0], LIVE_REGISTRATION[0]] + [v[0] for v in BACKGROUND_VOTERS]
)

TITLE_CLOSED = DEMO_PREFIX + "Library Committee Election 2025"
TITLE_OPEN_A = DEMO_PREFIX + "Student Council Election 2026"
TITLE_OPEN_B = DEMO_PREFIX + "Hostel Representative Election 2026"
TITLE_OPEN_C = DEMO_PREFIX + "Sports Captain Election 2026"
