# DEMO_RUNBOOK.md — Live demonstration script

Kenyan Electronic Voting System (proof of concept). Everything below was run on
the presentation laptop (Windows 11, PowerShell, the project venv, PostgreSQL
**15.19** on `localhost:5434`) against the database **`evoting_demo`**, on
25 November 2026, unless it is listed in **§9 "Not verified"**. The six acts in
§A were rehearsed end to end in a real Chromium browser driven by Playwright
(headless). Test suite on this code: **290 passed, 0 skipped** with the
app-role password exported (286 passed, 4 skipped without it).

---

## 0. One-time setup (PowerShell, from `evoting_system\`)

Load the `DB_*` values from `.env` into this PowerShell session (values are
never printed):

```
Get-Content .env | Where-Object { $_ -match '^\s*DB_' } | ForEach-Object { $k, $v = $_ -split '=', 2; Set-Item "env:$($k.Trim())" $v.Trim().Trim('"') }
$env:DB_NAME = "evoting_demo"; $env:DJANGO_SETTINGS_MODULE = "config.settings.demo"
$env:PGPASSWORD = $env:DB_PASSWORD
```

Then, once (these are the commands that were run):

```
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -h localhost -p 5434 -U evoting_user -d postgres -c "CREATE DATABASE evoting_demo OWNER evoting_user"
python manage.py migrate
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -h localhost -p 5434 -U evoting_user -d evoting_demo -v ON_ERROR_STOP=1 -v "app_password=$env:DB_APP_PASSWORD" -f scripts\setup_db_roles.sql
python manage.py seed_demo --with-admin
Remove-Item Env:PGPASSWORD
```

| Setting | Value on this machine |
|---|---|
| Database | `evoting_demo` (the dev database `evoting_dev` is not used for the demo) |
| Host / port | `localhost` / `5434` (PostgreSQL 15.19; PG 11 on 5433 and PG 16 on 5432 are other services, not used) |
| Owner role (migrations, `seed_demo`, `reset_demo`, tamper act) | `evoting_user` |
| Restricted runtime role (the web server) | `evoting_app` |
| `.env` | `DJANGO_DEBUG=True` (the on-page mock OTP needs it), `DB_APP_USER` / `DB_APP_PASSWORD` set |

**Start the server as the restricted role** (FR-DB-01, as production does):

```
$env:DEMO_DB_AS_APP = "1"; python manage.py runserver 127.0.0.1:8000
```

`DEMO_DB_AS_APP=1` makes `config.settings.demo` connect as `DB_APP_USER`. Verified:
while the server served a request, `pg_stat_activity` showed only `evoting_app`
connected to `evoting_demo`. **Run `seed_demo` / `reset_demo` without it** (they
need the owner): `Remove-Item Env:DEMO_DB_AS_APP` first. Base URL: `http://127.0.0.1:8000`.

**Reset and reseed between rehearsals** (server stopped; one line):

```
Remove-Item Env:DEMO_DB_AS_APP -ErrorAction SilentlyContinue; python manage.py reset_demo --yes; if ($?) { python manage.py seed_demo --with-admin }
```

**The demo works offline.** Tailwind (3.4.17 with the forms and container-queries
plugins) and the fonts (Inter, JetBrains Mono, Material Symbols Outlined) are served
from `static/vendor/` (commit `bf57fdf`; sources and licences in `THIRD_PARTY.md`).
Tested with every non-localhost request blocked: the nine key pages render the same
as online, with no request to any other host. If a template starts using a **new
Material Symbols icon**, re-download the subset font with that icon added to
`icon_names` (see `THIRD_PARTY.md`); otherwise its name shows as a word.

---

## A. Defence demo, six acts

Accounts (demo only; staff password for all: `DemoPass-2026!`, the seed default):

| Who | Login |
|---|---|
| Voter 1 (**not** voted) | National ID `39000001`, phone `+254700000001` |
| Voter 2 (**has** voted in Student Council) | National ID `39000002`, phone `+254700000002` |
| Live registration | National ID `39000099`, name "Live Demo Registrant", phone `+254700000099` |
| Official | `demo.official` (Staff login → lands on `/officials/overview/`) |
| Auditor | `demo.auditor` (Staff login → lands on `/auditors/`) |
| Administrator (superuser) | `demo.admin` |

Rehearsal timings are for the scripted steps (browser automation), not for talking.

### Act 1 — Register, then log in with the OTP (FR-V-00, FR-V-01, FR-V-03, FR-S-01) · scripted 6–9 s
1. Open `http://127.0.0.1:8000/` → **Register as a Voter** → `39000099`, `Live Demo Registrant`, `+254700000099` → submit.
   *Expected (seen):* "Registration complete".
2. **Voter login** in the bar → `39000001` / `+254700000001` → submit → `/voters/verify-otp/` shows
   `Shown only because DEBUG is on. Mock OTP: NNNNNN` (§3). The server console prints
   `[INFO] voters.sms_gateway: Stub SMS gateway: delivering OTP NNNNNN to +254700000001`.
3. Enter a wrong code first → *"Incorrect OTP."* Then the shown code → *"Session established"* (token valid about 15 minutes).

### Act 2 — Cast, then try again, then Voter 2 (FR-V-02, FR-V-04…08) · scripted 7 s
1. Click **Ballot** → Student Council Election 2026, three candidates. Click a candidate card → **Submit your ballot**.
   *Expected (seen):* "Your ballot has been recorded" with the ballot reference (UUID) and the audit hash digest (SHA-256). Because Student Council is the only open election, the page also shows the "All ballots cast" panel and the session ends (covered by tests; the rehearsal script did not check the panel text).
2. Second attempt: press **Back**. The browser asks the server for the ballot page again and gets
   *"Ballot not recorded — You need to log in before casting a ballot."* No second ballot exists.
3. New private window → **Voter login** → `39000002` / `+254700000002`.
   *Expected (seen):* "This voter has already cast a ballot." and no OTP is issued.

### Act 3 — Public tally and the re-check (FR-P-01, FR-P-02, FR-P-03) · scripted 4 s
1. **Public results** (`/tally/`): Library Committee Election 2025 shows **View verification →**; Student Council (OPEN) shows **Not yet published** and no link (FR-EL-03).
2. Library Committee: three candidate counts adding to **= 6** with *"✓ Confirmed"* (the order of the three numbers follows candidate IDs and changes on each reseed; this run showed `1 + 2 + 3 = 6`). Section 2 says the pairing check *"was not re-run for this page load (it passed when the results were published…)"*.
3. Click **Run the full independent check** (`?reverify=1`) → *"Overall: ✓ fully verified"* (seen). A repeat within 60 seconds shows a *"Cached result: this pairing check ran at …"* note while the other checks still run (covered by tests; not clicked in the rehearsal).
4. JSON: `http://127.0.0.1:8000/api/tally/<library-id>/` → keys `available, election_id, election_title, election_status, reason_unavailable, total_ballots, candidate_results, published_at, proof, verification, audit_entries`; `total_ballots` 6; each candidate result has only `candidate_id, name, count`.

### Act 4 — Official closes and publishes; Auditor checks (FR-A-03, FR-EL-03, FR-OFF-*, FR-AUD-01…03) · scripted 15 s
1. Log out (or new window) → **Staff login** as `demo.official` → lands on `/officials/overview/`.
2. **Elections** → Student Council row → **Close voting**. This posts to the Django admin action and lands on the admin page `/admin/elections/election/` with *"Closed '[DEMO] Student Council Election 2026'."* (admin pages have no green bar: type `http://127.0.0.1:8000/officials/elections/` to go back).
3. Student Council row → **Publish results** → confirmation page → **Publish results** → the public verify page for Student Council with its tally and *"✓ Confirmed"*.
4. As the Official open `http://127.0.0.1:8000/auditors/` → **403**.
5. **Logout** → **Staff login** as `demo.auditor` → `/auditors/`. **Audit log** lists `ballot_cast` entries (time, action, hashes; no voter data). **Verify chain** → *"Chain intact across all 8 entries, and every entry matches its ballot."* (8 = 6 Library + Voter 2 + Voter 1). **Compliance** → *"9 of 10 criteria met · 1 not met"*.

### Act 5 — The database refuses the application role (FR-DB-01, FR-P-03) · scripted under 1 s
```
$env:PGPASSWORD = $env:DB_APP_PASSWORD
& "C:\Program Files\PostgreSQL\15\bin\psql.exe" -h localhost -p 5434 -U evoting_app -d evoting_demo
```
```
UPDATE auditlog_auditlog SET ballot_hash = 'x';                 -- ERROR:  permission denied for table auditlog_auditlog
DELETE FROM auditlog_auditlog;                                   -- ERROR:  permission denied for table auditlog_auditlog
UPDATE ballots_ballot SET candidate_id = candidate_id;           -- ERROR:  permission denied for table ballots_ballot
DELETE FROM ballots_ballot;                                      -- ERROR:  permission denied for table ballots_ballot
UPDATE tally_electionresult SET total_ballots = total_ballots;   -- ERROR:  permission denied for table tally_electionresult
DELETE FROM tally_electionresult;                                -- ERROR:  permission denied for table tally_electionresult
\dp (auditlog_auditlog|ballots_ballot|tally_electionresult)
\d ballots_ballot
SELECT count(*) AS voters, min(length(national_id_hash)), max(length(national_id_hash)) FROM voters_voter;
```
Real output of `\dp`:
```
 public | auditlog_auditlog    | table | evoting_user=arwdDxt/evoting_user+
        |                      |       | evoting_app=ar/evoting_user
 public | ballots_ballot       | table | evoting_user=arwdDxt/evoting_user+
        |                      |       | evoting_app=ar/evoting_user
 public | tally_electionresult | table | evoting_user=arwdDxt/evoting_user+
        |                      |       | evoting_app=ar/evoting_user
```
`a` = INSERT, `r` = SELECT; `evoting_app` has no `w` (UPDATE) or `d` (DELETE). `\d ballots_ballot` shows only `ballot_id, created_at, candidate_id, election_id` (no voter or session column); foreign keys only to `elections_candidate` and `elections_election`; referenced only by `auditlog_auditlog`. The hash query returned `voters 9, min 64, max 64` (SHA-256 hex). End with `\q` and `Remove-Item Env:PGPASSWORD`.

### Act 6 — Tamper test on a COPY (FR-AUD-02) · scripted 46 s including the copy server start
> **Never on `evoting_demo` or any database that matters.** Stop `runserver` first (a template database cannot have other connections).

```
$env:PGPASSWORD = $env:DB_PASSWORD
$psql = "C:\Program Files\PostgreSQL\15\bin\psql.exe"
& $psql -h localhost -p 5434 -U evoting_user -d postgres -c "CREATE DATABASE evoting_demo_copy TEMPLATE evoting_demo"
$env:DB_NAME = "evoting_demo_copy"; $env:DEMO_DB_AS_APP = "1"; python manage.py runserver 127.0.0.1:8766
```
In a browser: `http://127.0.0.1:8766/` → Staff login `demo.auditor` → **Verify chain** → "Chain intact across all 8 entries, and every entry matches its ballot."
In a second PowerShell (owner role, on the copy), find the newest entry and save it:
```
& $psql -h localhost -p 5434 -U evoting_user -d evoting_demo_copy
SELECT max(log_id) FROM auditlog_auditlog;                                        -- call it N
CREATE TABLE saved_entry AS SELECT * FROM auditlog_auditlog WHERE log_id = N;
```
1. **Alter the LAST audit hash:** `UPDATE auditlog_auditlog SET ballot_hash = repeat('0',64) WHERE log_id = N;` → reload **Verify chain**:
   *"1 audit entry no longer matches the ballot it records (log_id N): the ballot was changed after it was recorded, or the entry's hash was altered."*
   Restore: `UPDATE auditlog_auditlog a SET ballot_hash = s.ballot_hash FROM saved_entry s WHERE a.log_id = s.log_id;` → intact again.
2. **Delete the NEWEST audit entry:** `DELETE FROM auditlog_auditlog WHERE log_id = N;` → reload:
   *"1 ballot has no audit entry: a ballot was added outside the voting process, or its audit entry was deleted."*
   Restore: `INSERT INTO auditlog_auditlog SELECT * FROM saved_entry; DROP TABLE saved_entry;` → intact again.
3. Clean up: stop the copy server; `& $psql -h localhost -p 5434 -U evoting_user -d postgres -c "DROP DATABASE evoting_demo_copy"`; `$env:DB_NAME = "evoting_demo"`; `Remove-Item Env:PGPASSWORD`.

(Both were verified in the rehearsal, log_id 23 in that run. Altering a hash in the **middle** of the chain is also detected, as a broken link at the next entry.) Limit to say aloud: a database **owner** who rewrites ballots **and** the whole audit chain consistently is not detected — the hashes have no secret key and nothing is anchored outside the database.

---

## 1. Seed-data helper

```
python manage.py seed_demo --with-admin                      # scenario "single" (default; the six acts)
python manage.py seed_demo --scenario chooser --with-admin
python manage.py seed_demo --scenario cycle --with-admin     # FR-EL-07
python manage.py reset_demo --yes                            # back to a clean state (owner role)
```

They use the application's own code paths (`create_user` + group, `open_voting()`,
the real `cast_ballot()` with a real token, the real `publish_results()`); `seed_demo`
only INSERTs into the audit log. Both refuse to run unless `DEBUG` is on.

| Scenario | State after seeding |
|---|---|
| `single` (default) | **Student Council Election 2026** OPEN (3 candidates); **Library Committee Election 2025** CLOSED + PUBLISHED (6 ballots); **Hostel Representative** and **Sports Captain** DRAFT with candidates. Voter 2 has voted in Student Council. |
| `cycle` | **President 2026** and **Governor 2026** OPEN; Library Committee CLOSED + PUBLISHED. Voter 2 has voted in President only. |
| `chooser` | **Hostel Representative** and **Sports Captain** OPEN (chooser appears); Library Committee CLOSED + PUBLISHED. Voter 2 has voted in Hostel Representative. |

Six "Demo Background Voter" records (`39000101`–`39000106`) give the closed election
a non-trivial tally, so the Officials overview shows turnout out of 8 registered voters
(2 of 8 = 25.0% after Voter 1 has voted, seen in the rehearsal).

**Reset** deletes only demo rows and aborts if the audit log holds any row that is not a
demo ballot. It needs the **owner** role: run as `evoting_app` it fails with
`permission denied` (FR-DB-01 working).

---

## 2. Moving around by clicking (FR-NAV-01)

| Who is looking | Links in the green bar |
|---|---|
| Anonymous | Home, Public results, Privacy, Voter login, Staff login |
| Voter after OTP | Ballot, Public results, **End session** (a button) |
| Official | Overview, Elections, Candidates, Public results, **Logout** |
| Auditor | Audit log, Verify chain, Compliance, Public results, **Logout** |

Logout and End session are POST buttons; typing their URLs gives 405. Django admin pages
(`/admin/…`, including the staff login form) have no bar.

---

## 3. The mock OTP — exactly where it appears (measured)

| | `config.settings.demo` | `config.settings.local` |
|---|---|---|
| On the OTP page (`Mock OTP: NNNNNN`, only when `DEBUG=True`) | yes | yes |
| Server console line `[INFO] voters.sms_gateway: Stub SMS gateway: delivering OTP NNNNNN to <phone>` | yes | **no** (no logging configured for that logger) |
| Plaintext code in the server-side session record (`django_session`) while debug mode shows it | yes | yes |
| Voter row | SHA-256 hash only, cleared after a correct OTP | same |

The privacy notice now says exactly this (corrected in commit `917a3ae`). The OTP is never
in the HTTP response of the credentials step; the page value comes from the session after the redirect.

---

## 4. Per requirement (reference while answering questions)

- **Privacy notice (FR-DPA-01)** `/voters/privacy/`: amber "academic prototype" box; what is collected and why; "Your ballot is not linked to you"; who can see what. Contact: **`jakin.kipkorir@gmail.com`**; retention: **"6 months after results are published"** (both from `voters/privacy.py`). No form; POST returns 405.
- **Registration uniqueness (FR-V-00):** registering `39000099` twice → "This National ID is already registered."
- **Atomic cast (FR-V-04…07):** one transaction records the ballot, appends the audit hash, deactivates the token and sets participation. Concurrent submissions of one token record one ballot; concurrent casts keep the chain linear (advisory lock); a cast in flight when the election is closed is either counted in the published tally or rejected (tests in `docs/TRACEABILITY.md`).
- **FR-V-05:** the token is **deactivated** (`is_active = f`), not deleted — see §6.
- **Administrator (FR-A-01…04):** `/admin/elections/election/add/` (page loads; not submitted, §9); an OPEN election's change page offers no new candidate rows; `cast_ballot` refuses ballots outside an open period.
- **Session hygiene (FR-SES-01…04, FR-NAV-01):** End session ends the token; a second login ends the first; absolute timeout (`VOTER_SESSION_ABSOLUTE_TIMEOUT_MINUTES`, default 30); 5 wrong OTPs lock that login ("Too many incorrect codes. Please start again."). Covered by tests; not clicked in this rehearsal.
- **FR-EL-05/06/07:** chooser and multi-ballot cycle — reseed with `--scenario chooser` or `--scenario cycle` (not re-run on this machine, §9).

---

## 5. Database facts (psql, owner or `evoting_app`)

Database `evoting_demo`, `localhost:5434`. Tables: `auditlog_auditlog`, `auditlog_authsecurityevent`,
`ballots_ballot`, `voters_voter`, `voter_sessions_session`, `voters_voterelectionparticipation`,
`elections_election`, `elections_candidate`, `tally_electionresult`.

- `evoting_app` is INSERT/SELECT only on `auditlog_auditlog`, `auditlog_authsecurityevent`, `ballots_ballot`, `tally_electionresult` (Act 5), and has full CRUD on the voter, session, participation, election and candidate tables.
- No structural link between ballots and voters (Act 5 `\d ballots_ballot`). Caution: `voted_at` and the ballot's `created_at` are written in the same transaction milliseconds apart; say "no structural link", not "impossible to correlate".
- The chain check (Verify chain, `?reverify=1`, publication) walks the links **and** recomputes each entry's hash from its ballot row **and** compares ballots with audit entries per election.

---

## 6. FR-V-05 — is the token deleted or deactivated?

**Deactivated, not deleted.** `ballots/services.py::cast_ballot` step 4 sets
`session.is_active = False` inside the same `@transaction.atomic` block as the ballot write;
the `voter_sessions_session` row stays (test `test_fr_v05_session_deactivated_not_deleted_after_cast`).
Step 1 accepts only an active, unexpired session and gives the same message for "used",
"expired" and "never existed". No ballot or audit field points at a session, so a retained
inactive row cannot reveal a choice.

If asked "how does that satisfy *destroy*?": *"I read destroy as 'make permanently unusable
in the same transaction'. The row is kept because `is_active` exists for exactly that, and
anonymity rests on there being no ballot-to-session link. Literal deletion would be a
one-line change (`session.delete()`) plus one test."* Present it as a documented design decision.

---

## 7. What cannot be shown live, and the evidence instead

| Item | Show instead |
|---|---|
| **TLS 1.3 (NFR-SE-01)** — the demo runs plain HTTP; the footer now reads "TLS 1.3 when deployed behind a proxy", which is a statement about deployment, not proof | `config/settings/production.py` (SSL redirect, secure cookies, HSTS, proxy header); TLS must be enforced by a reverse proxy; never deployed |
| MFA with a real SMS (FR-G-01) | §3 stub line and mock OTP; `voters/sms_gateway.py` |
| NFR-PE-01 Performance | Small single-machine dev-server measurement, **not a load test**: `C:\sectest\results\perf\` (default tally API p50 130 ms after the pairing fix) |
| NFR-US-01 Usability | No user study was held; the linear flow (Acts 1–2) and the accessibility snapshot only |
| NFR-AV-01 / NFR-SC-01 | Architecture only (app and DB tiers configured separately) |
| All requirements | `docs/TRACEABILITY.md`; `pytest`: **290 passed, 0 skipped** with `DB_APP_PASSWORD` exported |

---

## 8. Quick troubleshooting

- OTP not on the page → `DJANGO_DEBUG` is not `True`.
- No internet → nothing to do: the styling and fonts are local (`static/vendor/`). If a page shows unstyled text, check that `runserver` is serving static files (`DEBUG=True`) and that `static/vendor/` is present.
- An icon shows as a word (for example `how_to_vote`) → that icon is not in the subset font; re-download it with the name added to `icon_names` (`THIRD_PARTY.md`).
- `seed_demo` says data already present → run the reset line in §0.
- `reset_demo` says "permission denied" → `DEMO_DB_AS_APP` is still set (you are `evoting_app`); `Remove-Item Env:DEMO_DB_AS_APP`.
- `CREATE DATABASE … TEMPLATE` fails "being accessed by other users" → stop every server and psql session on `evoting_demo`.
- Officials **Close voting** lands on a Django admin page with no green bar → type `/officials/elections/` to return.

---

## 9. Not verified (after the 25 November 2026 rehearsal)

1. **By hand in a visible browser** — every click in the six acts was made by Playwright in headless Chromium 131; nobody watched a real Chrome/Edge window or the projector.
2. **Tamper act as `postgres` (superuser)** — run as the owner `evoting_user` only.
3. **Admin form submissions** — creating an election and candidates (FR-A-01/02): page load only.
4. **Dual-role chooser** `/post-login/choose/` — not run live.
5. **Receipt hash equals the audit-log row's hash** — not compared by eye.
6. **Expiry waits** — OTP (5 min), token (15 min), absolute timeout: covered by tests only.
7. **`chooser` and `cycle` scenarios, FR-SES clicks** — not re-run on this machine (earlier sandbox and tests only).
8. **Offline styling** — applied and tested headless (commit `bf57fdf`); not checked on the projector.
