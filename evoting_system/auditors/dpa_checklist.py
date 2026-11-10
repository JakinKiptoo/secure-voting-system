"""
FR-AUD-03 / Sprint 5: the ten-criterion Data Protection Act, 2019 (Kenya)
compliance checklist REQUIREMENTS.md §8 and CLAUDE.md's Sprint 5 roadmap
both call for, mapped to the specific component that actually satisfies
(or, honestly, does not yet satisfy) each one.

Kept as a plain data module, not inline in auditors/views.py, so
auditors/tests.py can import DPA_CHECKLIST directly and assert against
it (e.g. "every item has a status", "every 'met' item names a real
component") without needing to render a view first.

Each item's `status` is one of "met", "partial", "not_met" -- chosen
deliberately over a single boolean, because some criteria genuinely
are NOT met by this proof-of-concept (currently only item 8 below;
item 7 was also unmet until FR-DPA-01 added the privacy notice).
REQUIREMENTS.md §1 explicitly delimits voter education, data-subject
self-service, and policy work out of scope for this project, but a
Chapter 5 compliance checklist that quietly omitted the gaps instead of
reporting them would be the same kind of handover inaccuracy this
project has been guarding against throughout -- so any such gap is listed as
"not_met" with an honest reason, not left out or fudged to "met".

`status`/`component` below are deliberately code/architecture facts,
each traceable to a real file -- not restatements of DPA-2019 legal
text (this is a technical compliance checklist, not a legal opinion).
"""

DPA_CHECKLIST = [
    {
        "number": 1,
        "criterion": "Lawful basis & purpose limitation",
        "summary": (
            "Personal data collected only for voter eligibility and "
            "one-time authentication -- National ID, full name, phone "
            "number (FR-V-00) -- no secondary use anywhere in the "
            "system."
        ),
        "status": "met",
        "component": "voters/models.py::Voter; voters/views.py (registration view collects exactly these three fields, nothing else)",
    },
    {
        "number": 2,
        "criterion": "Data minimisation",
        "summary": (
            "Ballot carries no voter-identifying field at all, by "
            "schema design, not by query-time convention -- no FK from "
            "Ballot to Voter or Session, ever (CLAUDE.md invariant #1)."
        ),
        "status": "met",
        "component": "ballots/models.py::Ballot (no voter/session FK); SCHEMA.md's Ballot entity",
    },
    {
        "number": 3,
        "criterion": "Accuracy",
        "summary": (
            "National ID uniqueness is enforced at the PostgreSQL "
            "column level (not just application validation), and OTP "
            "re-verification confirms the voter controls the "
            "registered phone number before any ballot can be cast."
        ),
        "status": "met",
        "component": "voters/models.py::Voter.national_id_hash (unique=True); voters/views.py (OTP verification step)",
    },
    {
        "number": 4,
        "criterion": "Storage limitation",
        "summary": (
            "The session token is single-use and time-boxed (15-minute "
            "expiry, voter_sessions/services.py), and is explicitly "
            "deactivated the moment it's used, within the same atomic "
            "transaction that records the ballot (FR-V-05) -- it is "
            "never retained past the purpose it was issued for."
        ),
        "status": "met",
        "component": "voter_sessions/services.py::issue_session (SESSION_TOKEN_LIFETIME_MINUTES); ballots/services.py::cast_ballot step 4",
    },
    {
        "number": 5,
        "criterion": "Integrity & confidentiality of processing (security safeguards)",
        "summary": (
            "HTTPS/TLS 1.3 enforced end-to-end (NFR-SE-01), OTP "
            "secrets are hashed, not stored in plaintext, and the "
            "AuditLog table is insert-only at the PostgreSQL role "
            "level (FR-DB-01) -- a real GRANT/REVOKE, not an "
            "application-layer convention that a bug or a raw query "
            "could bypass."
        ),
        "status": "met",
        "component": "config/settings/production.py (TLS); voters/crypto_utils.py (hashing); scripts/setup_db_roles.sql (FR-DB-01 role GRANT/REVOKE)",
    },
    {
        "number": 6,
        "criterion": "Access restriction to authorised processing only",
        "summary": (
            "Officials and Auditors are two structurally separate, "
            "role-gated dashboards (FR-OFF-01/FR-AUD's own role "
            "check) -- Officials get operational status only, never "
            "ballot-level visibility (FR-A-05); Auditors get the "
            "AuditLog and chain-integrity tools only, never a "
            "Voter/Session/Ballot join (see the leak tests covering "
            "both dashboards)."
        ),
        "status": "met",
        "component": "officials/permissions.py::official_required; auditors/permissions.py::auditor_required",
    },
    {
        "number": 7,
        "criterion": "Transparency to the data subject (privacy notice at collection)",
        "summary": (
            "FR-DPA-01: a public, read-only privacy notice states what "
            "is collected (National ID as a SHA-256 hash only, full "
            "name, phone number, one-time passcodes, session token, "
            "per-election participation record, audit-log entry), why "
            "each item is collected, that a ballot is stored without a "
            "link to the voter, and who can see what. It is linked "
            "from the landing page and the login page, and summarised "
            "above the registration form, so it is shown before any "
            "personal data is entered. No consent checkbox is "
            "required. Still to be filled in by the project team: the "
            "contact email and the retention period are visible "
            "placeholders in voters/privacy.py, and the page says in "
            "its own text that it describes the prototype and is not "
            "a legal statement."
        ),
        "status": "met",
        "component": "voters/views.py::privacy_notice_view; templates/voters/privacy_notice.html; voters/privacy.py (controller/contact/retention); linked from templates/home.html, templates/voters/register.html, templates/voters/credentials.html",
    },
    {
        "number": 8,
        "criterion": "Data subject rights (access / correction / erasure self-service)",
        "summary": (
            "A voter has no self-service way to view, correct, or "
            "request erasure of their own registered data -- the only "
            "path to the Voter record is the Django admin, which is "
            "an administrator tool, not a data-subject-rights "
            "mechanism. REQUIREMENTS.md §1.6/§1.7 scope this project "
            "narrowly (no voter self-service beyond auth+voting), so "
            "this was a deliberate scope exclusion, not an oversight "
            "-- but it is still a real, unmet DPA-2019 criterion for a "
            "production system, and is reported as such rather than "
            "silently counted as covered."
        ),
        "status": "not_met",
        "component": "Out of scope per REQUIREMENTS.md §1.6/§1.7 -- no component implements this",
    },
    {
        "number": 9,
        "criterion": "Accountability (processing is independently verifiable, not just self-attested)",
        "summary": (
            "Every ballot-affecting write is hash-chained into "
            "AuditLog, each entry linking to the previous entry's "
            "hash, so the record of processing itself is tamper-"
            "evident rather than merely logged."
        ),
        "status": "met",
        "component": "auditlog/models.py::AuditLog (previous_hash chain); ballots/services.py::_compute_ballot_hash",
    },
    {
        "number": 10,
        "criterion": "Breach / tamper detection capability",
        "summary": (
            "The Auditor dashboard's chain-integrity check re-walks "
            "the entire AuditLog hash chain on demand and reports "
            "exactly where it breaks, giving a concrete technical "
            "mechanism for detecting unauthorised modification of "
            "processed data (FR-AUD-02) -- not just the insert-only "
            "DB grant (item 5) preventing it, but an active way to "
            "confirm it hasn't happened."
        ),
        "status": "met",
        "component": "auditors/services.py::verify_chain_integrity; auditors/views.py::verify_chain_view (FR-AUD-02)",
    },
]


def checklist_summary(checklist=DPA_CHECKLIST):
    """Small aggregate the template renders at the top of the page --
    kept as a function (not pre-computed at import time) so a test can
    call it against a modified list too, if one is ever needed."""
    met = sum(1 for item in checklist if item["status"] == "met")
    partial = sum(1 for item in checklist if item["status"] == "partial")
    not_met = sum(1 for item in checklist if item["status"] == "not_met")
    return {"total": len(checklist), "met": met, "partial": partial, "not_met": not_met}
