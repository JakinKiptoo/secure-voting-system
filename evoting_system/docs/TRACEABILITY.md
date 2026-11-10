# TRACEABILITY.md — Sprint 5 Final Traceability (Core + Extensions)

Per `EXTENSIONS_ROADMAP.md`'s own guardrail, these are kept as two
**separate** tables — extension IDs (`FR-OFF-*`, `FR-AUD-*`, `FR-EL-*`)
are never folded into the original `REQUIREMENTS.md` numbering, so
Chapter 5's traceability table for the core proposal stays exactly
matched to what was originally promised.

All test names/files below were confirmed against the actual Sprint 5
codebase (`sprint4_extract/evoting_system`), not reconstructed from
memory — see the handover for the full `pytest` run this is based on
(159 passed, 0 failed, 0 skipped after FR-DPA-01; it was 146
at the end of Sprint 5, and FR-DPA-01 added 13 tests).

## Part A — Core FR/NFR traceability (REQUIREMENTS.md)

| ID | Requirement | Test(s) / component | Coverage |
|---|---|---|---|
| FR-V-00 | Register with National ID, full name, phone; uniqueness; timestamp | `voters/tests.py::test_fr_v00_voter_creation`, `test_fr_v00_national_id_uniqueness_enforced_at_db_level`, `test_fr_v00_registration_view_creates_voter_and_rejects_duplicate` | Full |
| FR-V-01 | Accept National ID + phone as credentials | `voters/tests.py::test_fr_v01_credentials_view_rejects_unknown_voter`; `voters/test_fr_el_05.py` (credentials across elections) | Full |
| FR-V-02 | Check `has_voted` at authentication, reject if set | `voters/tests.py::test_fr_v02_credentials_view_rejects_already_voted_in_open_election`, `test_fr_v02_old_global_has_voted_no_longer_gates_login` | Full |
| FR-V-03 | Accept OTP, match hashed secret | `voters/tests.py::test_fr_v03_verify_otp_view_rejects_incorrect_otp`, `test_full_mfa_flow_issues_session_token` | Full |
| FR-V-04 | Accept exactly one ballot selection per session via UUID token | `ballots/tests.py::test_fr_v04_v08_cast_ballot_success_records_and_confirms` | Full |
| FR-V-05 | Destroy UUID token in the same atomic transaction | `ballots/tests.py::test_fr_v05_session_deactivated_not_deleted_after_cast`, `test_fr_v01_expired_session_rejected_before_any_transaction_work`, `test_cast_ballot_rejects_expired_session` | Full |
| FR-V-06 | Set `has_voted = True` in the same transaction | `ballots/tests.py::test_fr_v04_v08_cast_ballot_success_records_and_confirms` (Sprint 5: assertion now explicitly commented `# FR-V-06`, was previously covered but not individually ID-tagged — see §C.1) | Full |
| FR-V-07 | Generate SHA-256 hash, append to AuditLog, same transaction | `ballots/tests.py::test_fr_v04_v08_cast_ballot_success_records_and_confirms`, `test_audit_log_hash_chain_links_previous_hash` (Sprint 5: explicitly ID-tagged, see §C.1) | Full |
| FR-V-08 | Confirmation receipt with audit hash digest, post-commit | `ballots/tests.py::test_fr_v04_v08_cast_ballot_success_records_and_confirms`, `test_cast_ballot_view_full_flow_clears_session_token` | Full |
| FR-S-01 | Issue single-use, session-bound UUID token on MFA success | `voter_sessions/tests.py::test_fr_s01_issue_session_creates_single_use_token_bound_to_voter` (Sprint 5: new direct unit test, see §C.1), `voters/tests.py::test_full_mfa_flow_issues_session_token` | Full |
| FR-A-01 | Create election record (title, open/close times) | `elections/tests.py::test_fr_a01_election_creation` | Full |
| FR-A-02 | Register candidates before election opens | `elections/tests.py::test_fr_a02_candidate_creation` | Full |
| FR-A-03 | Open/close voting period; reject ballots outside it | `elections/tests.py::test_fr_a03_open_voting_transitions_draft_to_open`, `test_fr_a03_open_voting_rejects_non_draft_election`, `test_fr_a03_close_voting_transitions_open_to_closed`, `test_fr_a03_close_voting_rejects_draft_election`; `ballots/tests.py::test_cast_ballot_rejects_when_election_not_open` | Full |
| FR-A-04 | Block candidate add/modify once voting has opened | `elections/tests.py::test_fr_a04_candidate_locked_once_election_open`, `test_fr_a04_candidate_edit_locked_once_election_open` | Full |
| FR-A-05 | Operational status without exposing ballots/voter identities | No test literally named `fr_a05`, but the behavior is directly exercised by `officials/tests.py::test_overview_no_voter_session_ballot_detail_leaks`, `test_elections_view_no_voter_session_ballot_detail_leaks`, `test_results_view_no_voter_session_ballot_detail_leaks`, `test_dashboard_candidate_overview_has_no_per_candidate_vote_counts`; traced in comments at `voters/admin.py`, `ballots/admin.py`, `voter_sessions/admin.py`, `officials/views.py` | Full (behaviorally), ID-name gap noted in §C.2 |
| FR-P-01 | Unauthenticated public endpoint: tally, ZKP, AuditLog hashes | `tally/tests.py::test_public_verify_page_requires_no_authentication`, `test_public_api_endpoint_requires_no_authentication` | Full |
| FR-P-02 | Plain-language ZKP/tally presentation | `tally/tests.py` (item 5 block — internal-consistency tests) | Full |
| FR-P-03 | Nothing on the public endpoint reconstructs a voter's choice | `tally/tests.py::test_public_endpoint_no_voter_session_ballot_detail_leaks` (Sprint 5: context-walking bug fixed for real, see §C.1), `test_candidate_level_counts_do_not_reveal_which_ballot_was_whose` | Full |
| FR-G-01 | SMS Gateway routes OTP, confirms delivery | `voters/tests.py` (OTP dispatch via the stub gateway, full MFA flow test) | Full (stub gateway — no real carrier integration, out of scope per REQUIREMENTS.md §1) |
| FR-DB-01 | PostgreSQL blocks UPDATE/DELETE on AuditLog; INSERT only | `auditlog/tests.py::test_fr_db01_auditlog_insert_only_at_role_level` | Full (real role-level GRANT/REVOKE, not application-layer) |
| NFR-PE-01 | Performance: no perceptible delay on voter-facing requests | Traced in comments at `tally/services.py`, `tally/views.py`, `officials/views.py` (fast-path default `deep_verify=False`); not independently pytest-asserted (no load-test harness in this proof-of-concept — architectural provision only) | Comment-level only, see §C.2 |
| NFR-SE-01 | MFA, HTTPS/TLS 1.3, parameterised queries, insert-only audit log | Composite of FR-V-01/03 (MFA), FR-DB-01 (insert-only), §3.1 of `SECURITY_TESTING_PLAN.md` (zero raw SQL in application code, confirmed by grep); HTTPS/TLS traced in comments at `config/settings/base.py`, `local.py`, `production.py` | Full (as a composite); TLS itself is a deploy-time/infra claim, verified manually per `SECURITY_TESTING_PLAN.md` §2 Pass A |
| NFR-US-01 | Unassisted, linear, unambiguous voter flow | Traced in a new Sprint 5 comment at `voters/views.py` (module docstring); exercised end-to-end by `test_full_mfa_flow_issues_session_token` | Comment-level + indirect test, see §C.1 |
| NFR-AV-01 | App server + DB are the two failure points | Traced in a new Sprint 5 comment at `config/settings/base.py` (module docstring) — architectural, not independently testable by pytest | Comment-level only, see §C.2 |
| NFR-SC-01 | App/DB tiers scale independently | Traced in the same new Sprint 5 comment at `config/settings/base.py` — architectural provision only, not evaluated at national-scale concurrency per REQUIREMENTS.md §1 | Comment-level only, see §C.2 |
| NFR-MA-01 | Auth/casting/audit/tally stay in distinct modules | Traced in comment at `config/settings/base.py` (`INSTALLED_APPS` module boundary note); structurally evident from the six-app layout itself (`voters/`, `voter_sessions/`, `ballots/`, `tally/`, `auditlog/`, `elections/`) | Comment-level + structural, see §C.2 |

## Part B — Extension traceability (EXTENSIONS_ROADMAP.md)

| ID | What | Test(s) / component | Coverage |
|---|---|---|---|
| FR-OFF-01 | "Official" role (Group + is_staff check) | `officials/tests.py::test_official_group_exists_after_migration`, `test_is_official_requires_both_staff_and_group_membership`, `test_is_official_requires_group_not_just_staff`, `test_is_official_true_for_a_real_official` (section header at line 73: `# FR-OFF-01: the Role concept itself`) | Full |
| FR-OFF-02 | Overview (single most relevant election, stat-card summary) | `officials/tests.py::test_overview_handles_zero_elections`, `test_overview_handles_draft_only_election`, `test_overview_falls_back_to_most_recently_closed_election`, `test_overview_shows_turnout_and_candidate_count_for_open_election`, `test_overview_turnout_handles_zero_registered_voters` (section header: `# FR-OFF-02/FR-OFF-04: Overview content`) | Full |
| FR-OFF-03 | Candidates — read-only list, selectable by election | `officials/tests.py::test_candidates_view_defaults_to_the_overview_election`, `test_candidates_view_selector_reaches_any_election` (section header: `# Candidates view: FR-OFF-03`) | Full |
| FR-OFF-04 | Elections — every status, filterable/paginated, Open/Close quick-links | `officials/tests.py::test_elections_view_lists_a_draft_election_invisible_on_overview`, `test_elections_view_lists_all_statuses_together`, `test_elections_view_filters_by_status`, `test_elections_view_paginates`, `test_elections_view_shows_open_quick_link_only_for_draft_elections`; `ballots/test_fr_el_06_fix.py` (its own docstring cites FR-OFF-04 as the evidence multiple concurrent OPEN elections are a legitimate state) | Full |
| FR-OFF-05 | Officials-facing results view (display-only, reuses `get_verification_payload`) | `officials/tests.py::test_results_view_reuses_get_verification_payload_object_identity`, `test_results_view_requires_official_role`, `test_results_view_open_election_shows_no_results`, `test_results_view_closed_unpublished_shows_not_yet_published`, `test_results_view_closed_published_shows_counts_and_winner`, `test_results_view_no_voter_session_ballot_detail_leaks` | Full |
| FR-AUD-01 | Audit Log browser (paginated, filterable) | `auditors/tests.py` (pagination/filter tests, section covers log_id/action_type filters) | Full |
| FR-AUD-02 | Chain integrity check (hash-chain walk) | `auditors/tests.py` (chain-walk tests, incl. the shared-function-identity test vs. `tally/`) | Full |
| FR-AUD-03 | DPA-2019 checklist status | `auditors/tests.py::test_fr_aud03_dpa_checklist_renders_all_ten_real_criteria`, `test_fr_aud03_dpa_checklist_honestly_reports_unmet_criteria`, `test_fr_aud03_dpa_checklist_requires_auditor_role` (Sprint 5: placeholder replaced with real checklist, see §D). After FR-DPA-01 the checklist reads 9 of 10 criteria met, 1 not met (item 8, data-subject self-service, out of scope); item 7 moved from not met to met. `test_fr_aud03_dpa_checklist_honestly_reports_unmet_criteria` now expects exactly {8} | Full |
| FR-DPA-01 | Public privacy notice at collection (DPA-2019 checklist item 7): states what is collected and why, that ballots are unlinked from voters, and who can see what; GET only, no form, no database access; linked from the landing page, login page and above the registration form; controller/contact/retention text held in one constant | `voters/test_fr_dpa_01.py` (13 tests, all named `test_fr_dpa01_*`: reachable without login, prototype statement first, key disclosures, single-constant controller text, links on register/credentials/landing, no consent checkbox and forms unchanged, no voter/session/ballot data in body or context, no database writes, 405 on POST/PUT/PATCH/DELETE, no form, checklist item 7 cites the view); component: `voters/views.py::privacy_notice_view`, `templates/voters/privacy_notice.html`, `voters/privacy.py` | Full. Open placeholders: contact email and retention period (see handover) |
| FR-EL-05 | Per-election participation tracking (`VoterElectionParticipation`) | `voters/test_fr_el_05.py` (7 tests), `voters/tests.py` (login-across-elections tests), `ballots/tests.py::test_cast_ballot_rejects_already_voted_voter_in_same_election` | Full |
| FR-EL-06 Phase 1 | Investigation only: multi-OPEN-election gap observed, no fix | `ballots/test_fr_el_06_investigation.py::test_two_elections_can_be_open_simultaneously_and_voting_is_scoped_correctly` | Full (as an investigation — intentionally left untouched this sprint, per standing instruction) |
| FR-EL-06 Phase 2 | Fix: voter-facing election-chooser when >1 election OPEN | `ballots/test_fr_el_06_fix.py` (7 tests: unchanged 0/1-open path, chooser shown/filters correctly, stale/missing choice falls back to chooser, full end-to-end cast lands on chosen election) | Full |

## C — Notes

### C.1 — Gaps found and fixed this sprint

1. **`tally/tests.py::test_public_endpoint_no_voter_session_ballot_detail_leaks`**
   was crashing (`AttributeError: 'RequestContext' object has no
   attribute 'keys'`) across multiple prior sessions, each time
   reported as "pre-existing, unrelated" without being fixed. Root
   cause: `tally/verify.html` has never extended `base.html`, so
   Django's test client returns a bare `RequestContext` (no
   `.keys()`), not the `ContextList` every other leak test gets. Fixed
   **the test's own context-walking logic** (branch on `hasattr(context, "keys")`,
   fall back to `context.flatten()`) — not the application view/template,
   per the instruction that this specific fix was in scope. Confirmed
   passing in isolation, then as part of the full 146-test run.
2. **FR-S-01** had no direct unit test of `voter_sessions/services.py::issue_session()`
   itself — only indirect coverage through the full MFA-flow
   integration test. Added `voter_sessions/tests.py::test_fr_s01_issue_session_creates_single_use_token_bound_to_voter`.
3. **The landing page** (`config/views.py::home`, Thread D) had zero
   test coverage. Added `config/tests.py::test_home_page_renders_and_links_to_both_entry_points`,
   confirming it links to the real `voters:register`, `voters:credentials`,
   and `admin:login` routes.
4. **FR-V-06/FR-V-07** were behaviorally tested (`test_fr_v04_v08_cast_ballot_success_records_and_confirms`
   already asserted `has_voted` and the hash digest) but not
   individually ID-tagged — a grep for the literal string `"FR-V-06"`
   found zero matches in any test file before this sprint. Added
   inline `# FR-V-05` / `# FR-V-06` / `# FR-V-07` / `# FR-V-08` comments
   directly above each corresponding assertion in that same test, so
   each requirement is now independently greppable, without changing
   any assertion or adding a redundant test.
5. **NFR-US-01, NFR-AV-01, NFR-SC-01** had zero mentions anywhere in
   the codebase before this sprint (confirmed by grep across all
   `.py` files) — a real traceability gap under CLAUDE.md's rule that
   every ID "should be visible somewhere in the codebase... a
   docstring, a comment, or (best) a test name." These three are
   architectural/non-functional claims that don't reduce to a
   pass/fail pytest assertion (usability, failure-point count,
   independent tier scaling), so rather than writing a hollow test
   to force a checkmark, comment-level traceability was added at the
   component that actually embodies each claim: `voters/views.py`
   (NFR-US-01, the linear three-step auth flow) and
   `config/settings/base.py` (NFR-AV-01/NFR-SC-01, the three-tier
   architecture). See §C.2 for why these stay comment-level rather
   than test-level.
6. **Hardening tests added** (Sprint 5 prompt item 2's "confirm... no
   write/mutation" requirement): `tally/tests.py::test_fr_p01_public_api_endpoint_rejects_write_methods`
   (POST/PUT/PATCH/DELETE to `/api/tally/<id>/` all 405, zero rows
   changed) and `test_fr_p01_public_html_endpoint_post_performs_no_mutation`
   (POST to `/tally/<id>/` resolves — no `require_GET` — but mutates
   nothing). Neither existed before this sprint; both are new,
   genuine coverage, not a restatement of an existing test.

### C.2 — IDs with comment-level (not test-level) traceability, and why

Flagged explicitly, per the instruction to flag anything without test
coverage — none of these are **uncovered** in the sense of "untested
behavior"; all are cases where the ID itself names an architectural
property rather than a behavior a unit/integration test can assert on:

- **NFR-PE-01** (performance): the actual behavior ("don't do the slow
  `deep_verify` path by default") is structurally guaranteed by a
  default argument value (`deep_verify=False`) that every calling test
  already exercises implicitly — there's no meaningful latency
  assertion to add without a real load-testing harness, which is out
  of scope for this proof-of-concept (REQUIREMENTS.md §1.7).
- **NFR-AV-01 / NFR-SC-01** (availability / scalability): both are
  claims about the deployment topology (two tiers, independently
  scalable), not runtime behavior Django can expose to a test client.
- **NFR-MA-01** (maintainability): the six-module boundary is a
  structural fact about the repository layout itself, visible by
  inspection, not something to assert against at runtime.
- **FR-A-05**: *is* fully behaviorally tested (see Part A's row) — the
  gap here is narrower: the existing leak tests' names don't contain
  the literal substring `"FR-A-05"`, even though the file's own
  section comments and `admin.py` docstrings do reference it. Left
  as-is rather than renamed, since renaming four already-passing,
  independently-useful tests purely to add an ID substring would be
  test churn with no behavioral value — the comment-level trace
  already satisfies CLAUDE.md's "docstring, comment, or test name"
  (any one of the three, not all three).

No ID in either table has **zero** traceability (comment or test) —
this is the complete accounting.

## D — FRONTEND_STYLE.md deviation (logged, not fixed this sprint)

**Thread D's Tailwind-CDN-based template restyle
(`officials/`, `auditors/`, landing page, ballot-flow templates) is a
knowing, approved departure from `FRONTEND_STYLE.md`'s explicit
"Practical note for Django templates" guidance**: "Keep this to a
small shared base template + a couple of CSS custom properties for the
palette... rather than a component framework... A CSS-only approach
(no build step) is more consistent with that stated design goal than
pulling in a frontend framework." Thread D's templates instead load
Tailwind via the `cdn.tailwindcss.com` script tag and use Tailwind's
utility-class system throughout.

This is logged here as an explicit, named deviation rather than left
implicit, per this sprint's instruction — it is not something this
sprint corrects (doing so would mean rewriting every Thread D template
back to plain CSS, which is a feature-scale change, explicitly out of
scope: "Do NOT build any new feature — this sprint is tests,
documentation, and compliance artifacts only"). It should be weighed
by the student/supervisor against the actual visual-fidelity
trade-off Thread D achieved.

**Python version is explicitly NOT logged as a deviation**:
REQUIREMENTS.md §3 pins "Python 3.11" (no specific patch version). The
user has confirmed their own local machine runs 3.11.9; this session's
own verification environments (where the full suite above was
actually run) were 3.11.17 for Sprint 5 and 3.11.18 for FR-DPA-01 — both are Python 3.11, so both match the
spec exactly. Earlier sessions' SETUP.md language ("developed/verified
here on 3.12... switch to 3.11 if you want an exact match") is now
stale given this and should be read as superseded — Sprint 5's actual
verification ran under 3.11, not 3.12.
