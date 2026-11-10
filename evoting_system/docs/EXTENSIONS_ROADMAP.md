# EXTENSIONS_ROADMAP.md — Post-REQUIREMENTS.md Extensions

`REQUIREMENTS.md` is the frozen, supervisor-approved specification —
its `FR-*`/`NFR-*` IDs are not renumbered or extended retroactively.
Anything built on top of the core system that the frozen spec doesn't
itself call for — new operator-facing tooling, display-only
conveniences, anything that isn't FR-V/FR-S/FR-A/FR-P/FR-G/FR-DB/NFR-*
as written — is tracked here instead, under its own ID namespace, so
Chapter 5's traceability table for the *core* requirements stays exactly
matched to what the proposal actually promised, while this file carries
the paper trail for everything added beyond it.

**Note on this file's completeness**: the Officials Dashboard
(`FR-OFF-01` to `FR-OFF-04`) and Auditor Dashboard (`FR-AUD-01` to
`FR-AUD-03`) entries below are reconstructed from their own in-code
docstrings (`officials/permissions.py`, `officials/views.py`,
`auditors/views.py`) — verified against real code, not guessed. The
`FR-EL` section below was supplied directly and verified against the
real code this session; it is no longer a gap.

## FR-OFF — Officials Dashboard extension

| ID | What | Where |
|---|---|---|
| FR-OFF-01 | "Official" role — Django `Group` named `Official`, checked against `request.user` (`is_staff` + group membership), independent of the anonymous Voter/OTP flow | `officials/permissions.py`, `common/roles.py` |
| FR-OFF-02 | Overview — single most relevant election (current OPEN, else most recently CLOSED), stat-card summary (status/turnout/candidates/time) | `officials/views.py::overview_view` |
| FR-OFF-03 | Candidates — read-only candidate/position list, selectable by election | `officials/views.py::candidates_view` |
| FR-OFF-04 | Elections — every election regardless of status, filterable/paginated, with Open/Close voting quick-links | `officials/views.py::elections_view` |

## FR-AUD — Auditor Dashboard extension

| ID | What | Where |
|---|---|---|
| FR-AUD-01 | Audit Log browser — paginated, filterable `AuditLog` entries | `auditors/views.py::audit_log_list_view` |
| FR-AUD-02 | Chain integrity check — hash-chain walk over `AuditLog`'s own columns | `auditors/views.py::verify_chain_view`, `auditors/services.py` |
| FR-AUD-03 | DPA-2019 ten-criterion checklist status (real checklist since Sprint 5; 9 of 10 met, 1 not met after FR-DPA-01) | `auditors/views.py::dpa_checklist_view`, `auditors/dpa_checklist.py` |

## FR-DPA — Data-protection extension

| ID | What | Where |
|---|---|---|
| FR-DPA-01 | Public privacy notice at collection (DPA-2019 checklist criterion 7): a read-only page stating what the prototype collects and why, that ballots are stored without a link to the voter, and who can see what | `voters/views.py::privacy_notice_view`, `voters/urls.py` (`voters:privacy`, `/voters/privacy/`), `templates/voters/privacy_notice.html`, `voters/privacy.py`; tests in `voters/test_fr_dpa_01.py` |

## FR-EL — Election-scoping extensions

| ID | What | Where |
|---|---|---|
| FR-EL-05 | Per-election participation tracking — a voter who voted in Election A can still authenticate and vote in Election B; still blocked from voting twice in the SAME election; VoterElectionParticipation has no FK to Candidate/Ballot in either direction (anonymity invariant) | voters/models.py::VoterElectionParticipation, voters/views.py, ballots/services.py; tests in voters/test_fr_el_05.py |
| FR-EL-06 | Investigated (Phase 1, exploratory only — no fix built): nothing in the model layer prevents two Elections being OPEN simultaneously; cast_ballot_view's `Election.objects.filter(status=OPEN).first()` arbitrarily shows a voter whichever one Postgres returns first, with no way to choose. Phase 2 (the actual fix) implemented this session — see below. | elections/models.py, ballots/views.py::cast_ballot_view; investigation in ballots/test_fr_el_06_investigation.py |

**FR-EL-05 status**: Implemented (pre-existing in the codebase; not
built this session).

**FR-EL-06 status**: Phase 1 investigated, Phase 2 implemented this
session.

### FR-EL-06 Phase 2 — resolving the multi-open-election gap

**Decision**: before writing any code, `REQUIREMENTS.md`, `CLAUDE.md`,
`SCHEMA.md`, and `DIAGRAMS.md` were checked for any invariant — stated
or structurally implied — that only one Election should ever be OPEN
at a time. None exists: nothing in the Election entity's definition,
its state-machine diagram, or the written requirements constrains
OPEN-election cardinality. Meanwhile `FR-OFF-04` (the Officials
dashboard's Elections view, above) already treats multiple
simultaneous elections of any status, OPEN included, as an ordinary,
filterable, paginated list — i.e. multiple concurrent OPEN elections
are a state the system is already built to support elsewhere, not an
edge case to be prevented.

Given that evidence, the chosen fix is **Direction 2**: give the voter
an explicit choice, not a model-level guard at `open_voting()`
rejecting a second OPEN election. A guard would have invented a new
restriction the spec never asked for, not enforced an existing one.

**What changed**: `ballots/views.py::cast_ballot_view` now queries all
currently-OPEN elections (fresh query per request, never cached).
- 0 or 1 OPEN elections: behavior is byte-for-byte unchanged from
  before — no chooser, same direct-to-ballot-form behavior.
- More than 1 OPEN election: the voter is shown a new
  election-selection step (`templates/ballots/choose_election.html`)
  before the ballot form. The chosen election travels via the
  `?election=<uuid>` query param (GET, from the chooser's links) or a
  hidden `election` field inside the ballot form's POST body, and is
  re-validated against the currently-OPEN set on every request — a
  stale or tampered value falls back to the chooser again, never
  silently defaults to any particular election.
- `ballots/services.py::cast_ballot()` required **no change** — Phase
  1's own investigation already proved it resolves the election from
  the submitted `candidate_id`, never from an independent "the open
  election" lookup of its own.

**Files**:
- `ballots/views.py` — `cast_ballot_view` rewritten with the
  multi-open-election branch; new helper `_resolve_requested_election`
- `templates/ballots/choose_election.html` (new)
- `templates/ballots/cast.html` — one line added, a hidden `election`
  input so the choice survives the POST
- `ballots/test_fr_el_06_fix.py` (new) — 7 regression tests covering
  the unchanged 0/1-open common case and the >1-open chooser path,
  including the stale-choice-falls-back-to-chooser race Phase 1 flagged
  as a real possibility. `ballots/test_fr_el_06_investigation.py`
  (Phase 1) was left untouched, as instructed — it still documents the
  original exploratory observation only.

**Verification performed this session**: `ballots/test_fr_el_06_fix.py`
run in isolation — 7/7 passed. Full project-wide `pytest` suite then
run against a real PostgreSQL instance with `FR-DB-01`'s role
restriction actually exercised — 139 passed, 1 failed. The 1 failure
(`tally/tests.py::test_public_endpoint_no_voter_session_ballot_detail_leaks`)
is the same pre-existing, already-documented defect noted under
`FR-OFF-05` below (confirmed unrelated to this change, reproduces
against the unmodified Sprint 4 baseline) — no new regressions. (That
failing test was fixed in Sprint 5; the suite has had no failures
since.)

## FR-DPA-01 — Privacy notice at collection

**Status**: Implemented and tested (159 passed, 0 failed, 0 skipped
for the full suite, with `DB_APP_PASSWORD` exported). Two visible
placeholders remain for the student to fill in — see below.

**What it is**: an extension on top of the core system, tracked under
its own ID. It does not touch `REQUIREMENTS.md` numbering, and it does
not change any form, validation, registration or authentication logic.
It closes DPA-2019 checklist criterion 7 ("Transparency to the data
subject (privacy notice at collection)"), which was "not met" until
now.

**The page**: `/voters/privacy/` (`voters:privacy`), served from the
voters app. Public and unauthenticated, GET only (every other method
answers 405), no form, no database access. Layout and styling match
the other voter pages (standalone Tailwind shell, same as
`register.html`); no new frontend dependency.

**What it says** (only what the code and `SCHEMA.md` show the system
doing):
- A prototype statement, first on the page: an academic prototype that
  uses test data only.
- Controller line, contact, and one sentence that in a real deployment
  the organising electoral body would be the controller and this
  software a processor on its instructions (no real electoral body
  named).
- What is collected and why: National ID (SHA-256 hash only), full
  name, phone number, registration time, one-time passcode (hash only,
  5-minute validity, cleared after successful entry; the stub SMS
  gateway logs the code and phone number rather than sending an SMS),
  the single-use session token (about 15 minutes, deactivated on
  casting), the per-election participation record, and the audit-log
  entry.
- That a ballot is stored without any link to the voter, with the
  anonymity guarantees as already documented in `CLAUDE.md`.
- Who can see what: public, Officials, Auditors, administrators.
- Retention (placeholder) and a plain statement that the prototype has
  no self-service view, correction or deletion of a voter's data.
- It makes no claim that the system is legally compliant with any law.

**Shown before collection**: a summary and link above the registration
form, a link on the credentials (login) page, and a link on the
landing page. There is no required consent checkbox.

**Single place for the controller text**: `voters/privacy.py`,
`PRIVACY_NOTICE_CONTROLLER` (`controller_line`, `contact`, `retention`).
Edit that one dict and the page changes.

**Placeholders for the student**:
- `contact`: `[UNIVERSITY EMAIL: to be filled in by the student]`
- `retention`: `[TO BE CONFIRMED BY THE PROJECT TEAM]`
- The controller line names Strathmore University; if the supervisor
  says it may not be named, change `controller_line` in the same file.

**DPA checklist**: criterion 7 changed from "not met" to "met", citing
`voters/views.py::privacy_notice_view` and
`templates/voters/privacy_notice.html`. Criterion 8 (data-subject
self-service) stays "not met": out of scope. The checklist now reads
9 of 10 met, 1 not met.

**Files**:
- `voters/privacy.py` (new), `voters/views.py::privacy_notice_view`,
  `voters/urls.py`, `templates/voters/privacy_notice.html` (new)
- `templates/voters/register.html`, `templates/voters/credentials.html`,
  `templates/home.html` — link/summary only
- `auditors/dpa_checklist.py` (criterion 7), `auditors/tests.py`
  (`test_fr_aud03_dpa_checklist_honestly_reports_unmet_criteria` now
  expects exactly {8})
- `voters/test_fr_dpa_01.py` (new, 13 tests, all named
  `test_fr_dpa01_*`)
- `docs/TRACEABILITY.md`, `docs/SECURITY_TESTING_PLAN.md` (endpoint 19),
  `SETUP.md` (test count)

**Not changed**: `cast_ballot`, `VoterElectionParticipation`, tally and
any anonymity-related code, and every `ballots/test_fr_el_06_*.py`
file.

## FR-OFF-05 — Officials results view

**Status**: Implemented and tested this session (not yet confirmed
merged into the live repository — see handover below).

**What it is**: a display-only results page for a single election,
reachable from the Officials dashboard's Elections list (a "View
results" link appears on each `CLOSED` election's row). It is an
extension on top of the core system — **not** a change to
`FR-P-01`/`FR-P-02`/`FR-P-03` (the public tally/ZKP/verification
endpoint, which is untouched) and **not** a new tally computation.

**Reuse, not reimplementation**: the view calls
`tally.services.get_verification_payload()` — the exact same function
`tally/views.py::public_verify_view` already calls for the public page
— with `deep_verify` left at its default `False`. No new query against
`Ballot`/`Voter`/`Session`/`AuditLog` is introduced anywhere in this
feature.

**Behavior** (per the three election states):

1. **CLOSED + PUBLISHED** — `payload.available` is `True`. Shows each
   candidate's name and vote count (`payload.candidate_results`),
   total ballots cast (`payload.total_ballots`), and highlights
   whichever candidate has the highest count as the winner. The
   winner is computed as `max(payload.candidate_results, key=lambda
   c: c["count"])` **inside the view** — a plain `max()` over data the
   public page already serves, not a new tally path.
2. **CLOSED but NOT YET PUBLISHED** — `payload.available` is `False`
   (the existing `FR-EL-03` publish gate inside
   `get_verification_payload()` itself, not a second gate added here).
   The template shows "Results not yet published" and
   `payload.reason_unavailable`'s existing text. No candidate names,
   counts, or winner are rendered in this state — there is no code
   path that peeks at the tally before publish.
3. **OPEN** (or `DRAFT`) — no results are shown at all: a plain
   "Results are available once this election has closed and been
   published" message, no payload data referenced.

**No new leak surface**: this view renders a subset of the identical
`VerificationPayload` the public, unauthenticated `tally:verify`
endpoint already serves — the same object `FR-P-03`'s leak test already
covers. A dedicated leak test
(`officials/tests.py::test_results_view_no_voter_session_ballot_detail_leaks`)
additionally confirms no `Voter`/`Session`/`Ballot` model instance
reaches the view's own context, consistent with every other officials
view's leak-test pattern.

**Files**:
- `officials/views.py::results_view` (new)
- `officials/urls.py` — `officials/elections/<uuid:election_id>/results/`, name `officials:results`
- `templates/officials/results.html` (new, extends `officials/_shell.html`)
- `templates/officials/elections.html` — one added link, `{% if election.status == "CLOSED" %}`
- `officials/tests.py` — 6 new tests: access control, the three election-state behaviors, the winner-equals-independent-`max()` check, object-identity proof that `results_view` imports the real `get_verification_payload` (not a fork), and the leak test

**Verification performed this session** (see chat handover for full
detail): full `pytest` suite run against a real PostgreSQL instance
with `FR-DB-01`'s role restriction actually exercised (not skipped) —
132 passed, 1 failed. The 1 failure
(`tally/tests.py::test_public_endpoint_no_voter_session_ballot_detail_leaks`)
is a pre-existing defect confirmed unrelated to this change (reproduces
identically against the unmodified Sprint 4 baseline) — see that
session's separate write-up. All 6 new `FR-OFF-05` tests pass; all 39
`officials/tests.py` tests pass; nothing else in the suite regressed.
(That failing test was fixed in Sprint 5.)
