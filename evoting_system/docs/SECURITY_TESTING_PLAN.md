# SECURITY_TESTING_PLAN.md — Sprint 5 Burp Suite / SQLMap Plan

REQUIREMENTS.md §8 calls for a Burp Suite (MITM simulation) pass and a
SQLMap (automated SQL-injection) pass, run by the student, as Chapter
5's security-testing evidence. This document is the concrete plan and
configuration to run both tools against the system **as it actually
exists today** — every endpoint, not just the original Sprint 2/3
voter flow — plus the code-level hardening already confirmed by
reading the source and, where practical, by a new automated test
(cited per item below). These tools cannot be run from this session;
everything below is what the student runs manually.

## 1. Full current endpoint inventory

| # | Path | Method(s) | Auth | Module/ID |
|---|---|---|---|---|
| 1 | `/` | GET | None | Landing page (Thread D) |
| 2 | `/voters/register/` | GET, POST | None (anonymous voter) | FR-V-00 |
| 3 | `/voters/login/` | GET, POST | None (anonymous voter) | FR-V-01, FR-V-02 |
| 4 | `/voters/verify-otp/` | GET, POST | Pending-session voter | FR-V-03, FR-G-01 |
| 5 | `/ballots/cast/` | GET, POST | Voting-token session | FR-V-04 to FR-V-08; FR-EL-06 Phase 2's election-chooser branch when >1 election is OPEN |
| 6 | `/admin/login/` | GET, POST | None (staff credentials) | Thread A Part 3 — staff login surface |
| 7 | `/admin/` (Django admin, all registered models) | GET, POST | Staff session | FR-A-01/02/03/04 |
| 8 | `/post-login/`, `/post-login/choose/` | GET | Staff session | Thread A Part 3 role redirect |
| 9 | `/officials/overview/`, `/officials/elections/`, `/officials/candidates/` | GET | Official role | FR-OFF-02/03/04 |
| 10 | `/officials/elections/<election_id>/results/` | GET | Official role | FR-OFF-05 |
| 11 | `/auditors/` | GET | Auditor role | FR-AUD dashboard landing |
| 12 | `/auditors/audit-log/` | GET | Auditor role | FR-AUD-01, filterable/paginated |
| 13 | `/auditors/audit-log/verify/` | GET | Auditor role | FR-AUD-02 |
| 14 | `/auditors/compliance/` | GET | Auditor role | FR-AUD-03, DPA-2019 checklist |
| 15 | `/tally/` | GET | None (public) | Tally index |
| 16 | `/tally/<election_id>/` | GET, (POST resolves but writes nothing — §3.4) | None (public) | FR-P-01, FR-P-02 |
| 17 | `/tally/<election_id>/publish/` | POST | Official or Auditor role | FR-EL-03 |
| 18 | `/api/tally/<election_id>/` | GET only (others 405 — §3.4) | None (public) | FR-P-01 JSON twin |
| 19 | `/voters/privacy/` | GET only (POST/PUT/PATCH/DELETE all 405) | None (public) | FR-DPA-01, privacy notice; static text, no form, no database access |

Districts 9–14 and 10 specifically are new since the original FR-V/FR-S
core and must be in-scope for both tools this time, not just the
Voter-facing flow (1–5).

## 2. Burp Suite Community Edition — MITM simulation plan

**Setup**
1. Run the dev server over HTTPS locally (self-signed cert is fine for
   this proof-of-concept pass — `runserver_plus --cert-file` via
   `django-extensions`, or a local `mkcert` cert + a TLS-terminating
   reverse proxy in front of `runserver`), since NFR-SE-01's HTTPS/TLS
   1.3 claim is specifically what this pass is testing — running Burp
   against plain HTTP would test nothing.
2. Point the browser at Burp's proxy (default `127.0.0.1:8080`),
   install Burp's CA cert in the browser so HTTPS traffic can be
   intercepted without a cert-mismatch warning masking the real test.
3. In Burp's Target > Scope, add the dev host so Proxy/Repeater/Scanner
   only touch this application, not unrelated traffic.

**Pass A — passive/traffic inspection (every endpoint in §1)**
- Walk every row in §1's table once through the browser with
  intercept on, confirming in Burp's Proxy history:
  - Every request after the TLS handshake is HTTPS, never a plaintext
    HTTP fallback (NFR-SE-01).
  - No `Set-Cookie` or response body anywhere contains a raw National
    ID, OTP secret, or password in cleartext — in particular inspect
    rows 2–5 (the credential/OTP/ballot flow) and row 7 (Django
    admin), since those are the only places such data could appear.
  - Row 16/18 (public tally) and row 12 (AuditLog browser) responses:
    confirm there is no `voter`, `session`, `national_id`, or similar
    key anywhere in the JSON/HTML — this is FR-P-03's own invariant,
    already pytest-covered (see §4), but worth eyeballing the actual
    wire traffic too since a serializer change could regress it in a
    way a test missed.
- Compare an authenticated row (9–14, 17) accessed **without** a
  session cookie (use Burp Repeater to strip the `sessionid` cookie
  and resend) — expect a redirect-to-login or 403, never the
  dashboard content. This is the MITM-relevant check: a
  session-fixation or cookie-theft attacker replaying a captured
  request with no valid session must not get in.

**Pass B — role-boundary tampering (Repeater)**
- Log in as an Official-only account, capture one request to an
  Auditor-only URL (row 12/13/14) in Repeater, resend it as-is (same
  cookies). Expect 403, confirming role separation holds even when an
  attacker has a valid-but-wrong-role session, not just no session.
- Repeat the reverse (Auditor-only account against Official-only URLs,
  row 9/10).
- Row 5's election-chooser (FR-EL-06 Phase 2): with two elections
  OPEN, capture the POST that casts a ballot, then in Repeater change
  the hidden `election` field to a *different* currently-OPEN
  election's UUID than the one whose candidate was actually selected
  (i.e. submit `election=B`'s UUID alongside `candidate=`A1's
  candidate id). Expected: `BallotForm`'s own `election=` scoping
  rejects a candidate that doesn't belong to the submitted election
  (invalid-choice form error), not a ballot recorded against the
  wrong election — this is the chooser's actual protection against
  the FR-EL-05 per-election-scoping-bypass concern item 2 of this
  sprint's prompt names.
- Row 17 (`tally:publish`): capture the POST as an authenticated
  Official, resend via Repeater with no `Referer`/no CSRF token
  (strip the `csrfmiddlewaretoken` field/cookie). Expect Django's CSRF
  protection to reject it (403), confirming the one state-changing
  authenticated POST endpoint outside the ballot/MFA flow is also
  CSRF-covered.

**Pass C — automated scan (optional, time-permitting)**
- Burp Community's manual Scanner is limited (no fully automated
  active scan in the free edition) — use Repeater/Intruder manually
  against rows 2–5's form fields (national ID, phone number, OTP,
  candidate selection) with a short payload list (`' OR '1'='1`,
  `<script>alert(1)</script>`, long strings, null bytes) and confirm
  every response is either a normal validation-error page or a 400,
  never a 500 traceback (DEBUG=False in production settings should
  already guarantee no traceback is ever shown regardless) and never
  a reflected, unescaped payload in the response body (Django's
  template auto-escaping is the code-level control here — confirmed
  by grep, §3.3).

## 3. SQLMap — SQL injection test plan

**Code-level hardening confirmed first (read, not run)**

3.1. `grep -rn "\.raw(\|cursor()\|execute(" --include="*.py"` across the
     entire application code (excluding tests) returns **zero
     matches** — every single database query in every app
     (`voters/`, `voter_sessions/`, `ballots/`, `elections/`, `tally/`,
     `auditlog/`, `officials/`, `auditors/`) goes through the Django
     ORM's `QuerySet` API, which parameterizes every value by
     construction. The only two places in the whole repository that
     open a raw `psycopg2` connection and call `cursor.execute()` with
     a literal SQL string are inside the test suite itself
     (`auditlog/tests.py::test_fr_db01_auditlog_insert_only_at_role_level`),
     and even those use `%s` placeholders with parameter lists
     (`cur.execute("UPDATE auditlog_auditlog SET action_type = %s WHERE log_id = %s", ["tampered", entry.log_id])`),
     never string interpolation/concatenation.

3.2. Because of 3.1, there is no endpoint in §1 where a URL path
     segment, query parameter, or POST field is ever concatenated into
     SQL text — SQLMap's job here is to independently confirm that
     from the outside, not to find a counter-example (none is
     expected), and to catch any future regression before Chapter 5 is
     finalised.

3.3. Django's template layer auto-escapes all context values by
     default (none of the templates under `templates/` use `|safe` on
     any field sourced from voter/admin input — confirmed by grep: `grep -rn "|safe" templates/` returns only the handful of instances of Django's OWN trusted helper output, never raw user input), so even a successful injection into a stored field (there is none) would still render HTML-escaped, not execute.

**Running SQLMap itself**

Target every GET endpoint in §1 that takes a URL parameter, and every
POST endpoint's form fields, since SQLMap needs a concrete
request to replay and mutate:

```bash
# Public, parameterized GET endpoints (no auth needed):
sqlmap -u "https://<host>/tally/<election_id>/" --batch --level=5 --risk=3
sqlmap -u "https://<host>/api/tally/<election_id>/" --batch --level=5 --risk=3

# Officials/Auditors paginated+filterable list views (row 9/12) --
# capture a real authenticated request's cookie first, then:
sqlmap -u "https://<host>/auditors/audit-log/?page=1&action_type=ballot_cast" \
  --cookie="sessionid=<captured-cookie>" --batch --level=5 --risk=3
sqlmap -u "https://<host>/officials/elections/?status=OPEN" \
  --cookie="sessionid=<captured-cookie>" --batch --level=5 --risk=3

# POST form endpoints -- save a captured raw request from Burp
# (Pass A above) to a file and replay it with -r, which is the
# correct way to fuzz POST bodies + CSRF token together:
sqlmap -r voters_login_request.txt --batch --level=5 --risk=3
sqlmap -r voters_verify_otp_request.txt --batch --level=5 --risk=3
sqlmap -r ballots_cast_request.txt --batch --level=5 --risk=3
sqlmap -r tally_publish_request.txt --batch --level=5 --risk=3
```

- `--level=5 --risk=3` is SQLMap's most thorough (and slowest) setting
  — appropriate here since every target is a dev/staging instance, not
  production traffic.
- Expected result for every target above: **no injectable parameter
  found**, consistent with 3.1–3.3. A finding here would be a real
  regression and should be reported back (per the "flag it back"
  instruction) rather than patched inline as part of this
  documentation-only sprint.
- The `<election_id>`/`<ballot_id>`/etc. UUID path segments are worth
  SQLMap's attention specifically because they're the one place
  user-controllable values reach a WHERE clause on every single
  request to that view — even though 3.1 already shows they're always
  parameterized via the ORM, this is exactly the kind of claim SQLMap
  exists to verify independently rather than trust from a code read
  alone.

## 4. Automated (pytest) hardening already in place

These are not substitutes for the manual Burp/SQLMap passes above —
REQUIREMENTS.md §8 explicitly separates "security" (Burp/SQLMap) from
"unit"/"integration" testing — but they are the pytest-level evidence
for the specific hardening claims item 2 of this sprint's prompt asked
to be confirmed:

- **Privacy notice (row 19) can't be used to read or change anything**: `voters/test_fr_dpa_01.py::test_fr_dpa01_notice_rejects_post_put_patch_delete` (all four methods 405, no Voter/Session/AuditLog/Ballot row changes), `test_fr_dpa01_notice_performs_no_database_writes` (a GET issues no INSERT/UPDATE/DELETE) and `test_fr_dpa01_notice_renders_no_voter_session_ballot_data` (planted voter, session, ballot and audit-log values never appear in the page or its context). In Burp, row 19 needs only a quick pass: confirm a POST returns 405 and that the page contains no form or CSRF token. SQLMap has no parameter to target on this page.
- **Public endpoint / its API twin can't be used for any
  write/mutation**: `tally/tests.py::test_fr_p01_public_api_endpoint_rejects_write_methods`
  (POST/PUT/PATCH/DELETE to `/api/tally/<id>/` all return 405, zero
  rows changed) and `test_fr_p01_public_html_endpoint_post_performs_no_mutation`
  (POST to `/tally/<id>/` resolves — no `require_GET` decorator — but
  changes nothing).
- **The election-chooser step can't bypass per-election participation
  scoping**: `ballots/test_fr_el_06_fix.py` (the chooser only ever
  offers currently-OPEN elections and re-validates the choice fresh on
  every request) combined with `ballots/services.py::cast_ballot`'s
  own FR-EL-05 `VoterElectionParticipation` re-check, which the
  chooser sits entirely in front of and never bypasses — the chooser
  picks *which* election's ballot form to show; it is `cast_ballot()`,
  unchanged by FR-EL-06 Phase 2, that still enforces one ballot per
  (voter, election) pair. `ballots/tests.py::test_cast_ballot_rejects_already_voted_voter_in_same_election`
  and `voters/test_fr_el_05.py` cover that enforcement directly.
- **No raw/unparameterized SQL anywhere in application code**:
  confirmed by the grep in §3.1 — not itself a pytest test (there's no
  meaningful assertion to write against "a grep found nothing"), but
  documented here as the code-level finding SQLMap's run is expected
  to independently corroborate.
