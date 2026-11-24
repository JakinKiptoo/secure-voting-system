# DEMO_RUNBOOK.md — Live demonstration script

Kenyan Electronic Voting System (proof of concept). Everything below was
run against a real local PostgreSQL and a live `runserver` unless it is
listed in **§9 "Not verified by running"**. Application behaviour is
unchanged: the demo tooling only adds data, never touches a constraint,
grant or permission.

---

## 0. One-time setup before the presentation

```
python manage.py migrate
```

1. `.env` must have `DJANGO_DEBUG=True` (the on-page mock OTP depends on it, §3),
   and `DB_APP_USER` / `DB_APP_PASSWORD` set to the restricted role created by
   `scripts/setup_db_roles.sql` (SETUP.md step 6).
2. The demo database is the dev database: **name `evoting_dev`, host
   `localhost`, port `5432`, owner role `evoting_user`, restricted app role
   `evoting_app`** (from `.env.example` and `scripts/setup_db_roles.sql`; use
   your own values if your `.env` differs).
3. Start the server for the demo with the demo settings (identical to local
   settings, plus console logging of the stub SMS gateway, §3):

   ```
   # bash
   DJANGO_SETTINGS_MODULE=config.settings.demo python manage.py runserver
   # PowerShell
   $env:DJANGO_SETTINGS_MODULE="config.settings.demo"; python manage.py runserver
   ```

   Base URL below: `http://127.0.0.1:8000`.

---

## 1. Seed-data helper

Two management commands (in `elections/management/commands/`).

```
python manage.py seed_demo --with-admin             # scenario "single" (default)
python manage.py seed_demo --scenario chooser --with-admin
python manage.py seed_demo --scenario cycle --with-admin     # FR-EL-07 demo
python manage.py reset_demo --yes                    # back to a clean state
```

**How they stay honest.** They use the application's own code paths only:
staff accounts via `create_user` + group membership (`is_staff=True`, group
`Official` / `Auditor`; the Auditor group has no migration so it is
`get_or_create`d); candidates are created while the election is DRAFT and
then `open_voting()` is called (FR-A-03/FR-A-04 respected); every ballot is cast
through the real `cast_ballot()` with a real `issue_session()` token, so the
audit hash chain, participation rows and session deactivation are genuine; the
closed election is published with the real `publish_results()`. `seed_demo`
only INSERTs into the audit log. Both refuse to run unless `DEBUG` is on.
Nothing edits grants, constraints, models or permissions.

**Why several scenarios.** An election cannot go back from OPEN to DRAFT, and
FR-EL-06's chooser appears only when more than one election is OPEN, so "one
open election" and "two open elections" cannot both be the starting state.

| Scenario | State after seeding |
|---|---|
| `single` (default) | **Student Council Election 2026** OPEN (3 candidates); **Library Committee Election 2025** CLOSED + PUBLISHED (6 ballots); **Hostel Representative** and **Sports Captain** left DRAFT with candidates (an Official opens them live, §4 FR-A-03, which then produces the chooser). Voter 2 has voted in Student Council. |
| `cycle` | **President 2026** and **Governor 2026** both OPEN (FR-EL-07: one login, two ballots; President is first because it starts earlier); **Library Committee** CLOSED + PUBLISHED. Voter 2 has voted in **President** only, so Governor is still pending for them. |
| `chooser` | **Hostel Representative** and **Sports Captain** both OPEN (chooser appears); **Library Committee** CLOSED + PUBLISHED; no Student Council. Voter 2 has voted in Hostel Representative. |

**Accounts** (demo only; password for all staff: `DemoPass-2026!`, override with `--password`):

| Who | Login | Where |
|---|---|---|
| Official | `demo.official` | `/admin/login/` → lands on `/officials/overview/` |
| Auditor | `demo.auditor` | `/admin/login/` → lands on `/auditors/` |
| Administrator (superuser, only with `--with-admin`) | `demo.admin` | `/admin/` — needed for FR-A-01/02. The Official group holds only `change_election` (verified: Official gets 403 on "add election"). |
| Voter 1 (**not** voted) | National ID `39000001`, phone `+254700000001` | `/voters/login/` |
| Voter 2 (**has** voted) | National ID `39000002`, phone `+254700000002` | `/voters/login/` |
| Live-registration ID | National ID `39000099`, name "Live Demo Registrant", phone `+254700000099` | register this one on stage (FR-V-00); `reset_demo` removes it |

Six "Demo Background Voter" records (IDs `39000101`–`39000106`) exist only so
the closed election has a non-trivial tally. Because they are registered
voters, the Officials overview shows turnout "1 of 8 voters" (12.5%) in the
`single` scenario; that is correct, not a bug.

**Reset.** `reset_demo --yes` deletes only demo rows (elections titled
`[DEMO] …`, their ballots/audit rows/results/participation, the demo voters and
their sessions, the `demo.*` users). It aborts if the audit log contains any
row that is not a demo ballot, so it cannot silently break a real chain.
**Deleting audit rows needs the database owner role** (`DB_USER`, e.g.
`evoting_user`, which `manage.py` uses by default). Run as the restricted role it
fails with `permission denied` — verified — and that is FR-DB-01 working, not a
defect. Reset leaves the `Official`/`Auditor` groups and all grants alone.

Standard reset-and-reseed between rehearsals:
`python manage.py reset_demo --yes && python manage.py seed_demo --with-admin`

---

## 2. Moving around by clicking (FR-NAV-01)

Every page carries the same dark-green navigation bar. **Type only the first
URL (`http://127.0.0.1:8000/`); after that, click.** What the bar shows:

| Who is looking | Links |
|---|---|
| Anonymous | Home, Public results, Privacy, Voter login, Staff login |
| Voter mid-flow (after OTP) | Ballot, Public results, **End session** (a button) |
| Official | Overview, Elections, Candidates, Public results, **Logout** (a button) |
| Auditor | Audit log, Verify chain, Compliance, Public results, **Logout** |
| Staff account with no role (e.g. `demo.admin`) | Home, Administration, Public results, **Logout** |

Logout and End session are buttons that POST (with CSRF); typing their URLs
in the address bar gives "405 Method Not Allowed". To change role in the demo:
click **Logout**, then **Staff login**. To start over as a different voter:
click **End session** (or just use a private window).

The registration page is reached from the landing page ("Register as a Voter").
The Django admin's own pages (`/admin/…`, including the staff login form)
are Django's templates and do not have the bar; use the browser Back button or
the **Home** / **Administration** links to return.

---

## 2a. Suggested order (about 20 minutes)

1. §4.1 Landing + privacy notice → 2. §4.2 Register (FR-V-00) →
3. §4.3 Login/OTP/ballot as Voter 1 (FR-V-01…08, FR-S-01) →
4. §4.4 Voter 2 rejected (FR-V-02) → 5. §4.5 Public tally (FR-P-*) →
6. §4.6–4.8 Official, Auditor → 7. §5 psql database security →
8. §4.9 FR-EL-05/06 chooser (reseed `--scenario chooser` first) → 9. §6, §7 questions.

---

## 3. The mock OTP — exactly where it appears

Verified on a live server:

1. **On the page (this is what the audience sees).** After submitting National
   ID + phone at `/voters/login/`, the **"Verify OTP" page `/voters/verify-otp/`**
   shows `Shown only because DEBUG is on. Mock OTP: NNNNNN`. It is rendered
   only when `settings.DEBUG` is `True`; with `DEBUG=False` neither the session
   key nor the text exists.
2. **In the server console (only with the demo settings).** Starting the server
   with `config.settings.demo` prints
   `[INFO] voters.sms_gateway: Stub SMS gateway: delivering OTP 890912 to +254700000002`
   in the terminal running `runserver`. This is the "SMS gateway" output (FR-G-01).
3. **Not in the console with the normal settings.** I ran `runserver` with
   `config.settings.local` and searched its output: the stub's log line does
   **not** appear, because the project defines no `LOGGING` for that logger
   (INFO is dropped). So use the demo settings if you want to show the gateway
   line.
4. The OTP is never in the network response of the credentials step; the page
   value comes from the Django session after redirect.

> **Inconsistency to fix or avoid saying aloud.** The privacy notice
> (`templates/voters/privacy_notice.html`) and `EXTENSIONS_ROADMAP.md` say the code
> "is written to the server's application log". With the project's own settings
> it is not visible anywhere (item 3). Either keep using `config.settings.demo` when
> presenting, or change the notice wording to "passed to the server's logging
> system". I did not edit the notice (this task was documentation/tooling only).

---

## 4. Click-by-click, per requirement

All pages have the navigation bar (§2). Staff log in with **Staff login** (which is `/admin/login/`). Each step below says which link to click; typing a URL is needed only for the first page and for the `/tally/<id>/…` pages reached from a list.

### 4.1 Landing and privacy notice (FR-DPA-01)
- Open `/` (the one typed URL). Click **Privacy** in the bar → `/voters/privacy/`.
- *Expected:* first thing on the page is the amber box "This is an academic
  prototype that uses test data only." Sections: who is responsible, what is
  collected, "Your ballot is not linked to you", who can see what, retention.
  Contact (`jakin.kipkorir@gmail.com`) and retention ("6 months after results
  are published") are filled in (`voters/privacy.py`). No form;
  POST/PUT/PATCH/DELETE return 405.
- Also linked above the registration form and on `/voters/login/`.

### 4.2 FR-V-00 Registration
- `/voters/register/` → enter `39000099`, "Live Demo Registrant", `+254700000099` → Submit.
- *Expected:* "Registration complete — Your voter record has been created."
- Submit the same National ID again → *Expected:* "This National ID is already registered." (uniqueness).
- Timestamp: psql `SELECT full_name, registration_date FROM voters_voter WHERE full_name LIKE 'Live%';` shows a timestamp.

### 4.3 FR-V-01, FR-V-03, FR-S-01, FR-V-04…08 — Voter 1 votes
(scenario `single`; Student Council is the only OPEN election.)
1. Click **Voter login** → `39000001` / `+254700000001`. *Wrong phone → "Invalid credentials." (FR-V-01).*
2. Redirects to `/voters/verify-otp/`; the mock OTP is on the page (§3).
3. Enter a wrong 6-digit code first → "Incorrect OTP." (FR-V-03). Then the correct one.
4. *Expected:* "session established" page showing the token expiry (about 15 minutes) — FR-S-01. The token itself is only in the browser session, never displayed.
5. The bar now shows **Ballot** and **End session**. Click **Ballot** (`/ballots/cast/`). Three candidates, no chooser. Pick one → Submit.
6. *Expected:* "Ballot Confirmed" page with the ballot id and the **audit hash digest** (FR-V-08).
7. Press Back and resubmit (or re-POST `/ballots/cast/`) → *Expected:* "Ballot Rejected" page (FR-V-04: one ballot per session; the token is now inactive, §6).
8. Evidence for the atomic steps (FR-V-05/06/07), see §5 for the psql login:
   - `SELECT left(uuid_token::text,8) AS token, is_active FROM voter_sessions_session;` → the used token has `is_active = f`.
   - `SELECT full_name, has_voted FROM voters_voter;` → Voter 1 now `t`.
   - `SELECT * FROM voters_voterelectionparticipation;` → a row with `has_voted = t` and `voted_at`; no candidate or ballot column.
   - Auditor `/auditors/audit-log/` → new top entry; its `ballot_hash` is the digest on the receipt (I confirmed the receipt renders the hash from the audit entry in code and tests; I did not compare the two by eye in the live run).

### 4.4 FR-V-02 Already voted
- New private window → `/` → **Voter login** → `39000002` / `+254700000002`.
- *Expected (`single`):* rejection page "This voter has already cast a ballot." No OTP is issued.
- After step 4.3, Voter 1 gets the same rejection.

### 4.5 Public Verifier — FR-P-01, FR-P-02, FR-P-03 (no login)
- Click **Public results** → `/tally/` lists elections. Open **Library Committee Election 2025** → `/tally/<id>/`.
- *Expected:* tally with a plain-language check "1 + 3 + 2 = 6 ✓ Confirmed — the published candidate counts sum to the published total", the ZKP data and audit hashes.
- `/api/tally/<id>/` (JSON). Keys: `available, election_id, election_title, election_status, reason_unavailable, total_ballots, candidate_results, published_at, proof, verification, audit_entries`; each candidate result has only `candidate_id, name, count`. No voter, session or ballot identifiers (FR-P-03).
- Open **Student Council Election 2026** (OPEN, unpublished) → *Expected:* "Results not yet published" (FR-EL-03 gate).

### 4.6 Administrator — FR-A-01…A-05 (log in at `/admin/login/` as `demo.admin`)
- **FR-A-01/02:** `/admin/elections/election/add/` → title, opening/closing times; add candidates (name, party, biography) in the inline; Save. *Page load verified; I did not submit this form.*
- **FR-A-03:** as `demo.official` (or admin) select an election in `/admin/elections/election/` → action **Open voting** / **Close voting**. *Expected:* status changes; opening an already-OPEN election shows "only a DRAFT election can be opened" (verified). Ballots outside an open period are refused by `cast_ballot` ("This election is not currently open for voting.").
- **FR-A-04:** open the OPEN election's change page (`/admin/elections/election/<id>/change/`). *Expected:* no "Add another candidate" row (verified: zero candidate inputs); enforced again in `Candidate.clean()`.
- **FR-A-05:** `/officials/overview/` (below) shows state and candidates, no ballots or voters' identities.

### 4.7 Officials — FR-OFF-01…05
- Click **Staff login**, sign in as `demo.official` → lands on `/officials/overview/` (FR-OFF-01 role redirect). As the Official, `/auditors/` returns **403** (verified); anonymous visits redirect to `/admin/login/?next=…` (verified).
- Click **Overview** (`/officials/overview/`) (FR-OFF-02): status, turnout, candidates, time remaining, window controls.
- Click **Candidates** (`/officials/candidates/`) (FR-OFF-03): read-only list, selectable by election.
- Click **Elections** (`/officials/elections/`) (FR-OFF-04): all elections, Open/Close quick-links, **View results** on CLOSED rows. *The quick-link buttons post to the admin action I exercised; I did not click the buttons themselves.*
- `/officials/elections/<id>/results/` (FR-OFF-05) for the Library election → counts and winner.
- **Publish (FR-EL-03, FR-OFF-06):** Close Student Council (Elections list **Close voting**) → click **Publish results** on its row (or on its results page) → confirmation page `/tally/<id>/publish/` → **Publish** → redirects to the public verify page, which now shows the tally (verified). Anonymous POST to the publish URL → 403 (verified).

### 4.8 Auditor — FR-AUD-01…03
- Click **Logout** (Official), then **Staff login** as `demo.auditor` → `/auditors/`. The bar shows Audit log, Verify chain, Compliance, Public results, Logout.
- Click **Audit log** (`/auditors/audit-log/`) (FR-AUD-01): paginated entries (time, action, hashes; no voter data).
- Click **Verify chain** (`/auditors/audit-log/verify/`) (FR-AUD-02): *Expected:* "Chain intact across all N entries."
- Click **Compliance** (`/auditors/compliance/`) (FR-AUD-03): "9 of 10 criteria met, 1 not met" (criterion 8, data-subject self-service, honestly "not met"). As the Auditor, `/officials/overview/` returns 403 (verified).
- A user in both groups gets a role chooser at `/post-login/choose/` (not verified live; §9).

### 4.10 Session hygiene — FR-SES-01, FR-SES-02, FR-SES-03 and FR-NAV-01
- **FR-NAV-01 (logout):** as Official or Auditor click **Logout**. *Expected:* back on the landing page showing the anonymous bar; clicking **Staff login** or going back to an Officials page asks you to log in again. (Checked in a real browser: login → Logout → redirected home → `/officials/overview/` redirects to the login page.) Typing `/staff/logout/` in the address bar → 405.
- **FR-SES-03 (End session):** log in as Voter 1 up to the "session established" page, then click **End session** in the bar. *Expected:* a "Session ended" page. Now press Back and click **Ballot**, or use the Back button to the ballot page → *"You need to log in before casting a ballot."* The old token is dead: psql `SELECT left(uuid_token::text,8), is_active FROM voter_sessions_session;` shows the row still exists with `is_active = f`.
- **FR-SES-01 (second login ends the first):** log in as Voter 1 in window A (stop at the "session established" page, do not vote). In a private window B log in as Voter 1 again. In psql the same query shows window A's token `f` and window B's token `t`. In window A click **Ballot** and submit a vote → *"Ballot Rejected"* (the first session was ended by the second login).
- **FR-SES-02 (absolute timeout):** with the default 30 minutes the token's own 15-minute expiry (FR-S-01) fires first, so to show this rule act set `VOTER_SESSION_ABSOLUTE_TIMEOUT_MINUTES=1` in `.env` and restart the server. Log in as Voter 1, wait over a minute, click **Ballot**. *Expected:* a "Session expired" page with a **Log in again** button; psql shows the token `is_active = f`. (Covered by tests; I did not wait it out in a browser.)

### 4.11 FR-EL-07 — voting in every open election in one login
Reseed: `reset_demo --yes` then `seed_demo --scenario cycle --with-admin`. (Verified in a real browser, with the sandbox's blocked Tailwind CDN, so styling was not checked.)
1. Click **Voter login** → Voter 1 (`39000001` / `+254700000001`) → OTP (§3) → click **Ballot**.
2. *Expected:* the **Your ballots** checklist: **President 2026 — Pending** then **Governor 2026 — Pending** (ordered by start time, then title).
3. Click **President 2026**, choose a candidate, **Submit**. *Expected:* the receipt (ballot reference + audit hash) and a panel "You have 1 more ballot to cast. Next: Governor 2026" with **Continue to next ballot**. No OTP is asked.
4. Optional: on a ballot form, **Skip for now** goes to the next pending ballot and records nothing.
5. Click **Continue to next ballot**, choose a candidate, **Submit**. *Expected:* the receipt plus an **All ballots cast** panel; the bar returns to the anonymous links, i.e. the session has ended.
6. **Resume:** log in as Voter 2 (who voted in President). *Expected:* checklist **President — Done**, **Governor — Pending**; only Governor can be voted. Or: vote President as Voter 1, click **End session** instead of continuing, log in again, and the checklist shows President done.
7. Evidence (psql, §5): `SELECT left(uuid_token::text,8), is_active FROM voter_sessions_session;` shows one token per ballot, all `f`; `ballots_ballot` has one row per election with no column in common, and no table links the two ballots. (**FR-V-04 reading:** "one single-use token per pending election within one authenticated login" — flag for Ms. Siva's sign-off.)

### 4.9 FR-EL-05 and FR-EL-06
- **Chooser from `single`:** as Official open **Hostel Representative** and **Sports Captain** (§4.6) → login as Voter 1 → `/ballots/cast/` shows "Choose an Election" with all OPEN elections (verified: three links).
- **Or reseed:** `reset_demo --yes` then `seed_demo --scenario chooser`.
- **FR-EL-05 (per-election participation), verified in `chooser`:** login as Voter 2 (voted in Hostel). Login is allowed (a second open election is still unvoted). Choose **Hostel** → submit → *"This voter has already cast a ballot in this election."* Choose **Sports Captain** → submit → **Ballot Confirmed**.
- **FR-EL-06, one open election:** with `single`, no chooser appears (verified).

---

## 5. Database-security demo (real psql)

Values: database `evoting_dev`, host `localhost`, port `5432`, restricted role
`evoting_app`. Tables: `auditlog_auditlog`, `ballots_ballot`, `voters_voter`,
`voter_sessions_session`, `voters_voterelectionparticipation`,
`elections_election`, `elections_candidate`, `tally_electionresult`.
All outputs below are real (PostgreSQL 16.x in my sandbox; your spec is 15).

```
# bash:        export PGPASSWORD='<DB_APP_PASSWORD>'
# PowerShell:  $env:PGPASSWORD='<DB_APP_PASSWORD>'
psql -h localhost -p 5432 -U evoting_app -d evoting_dev
```

### 5a. Insert-only audit log (FR-DB-01)
```
UPDATE auditlog_auditlog SET ballot_hash = 'x';
DELETE FROM auditlog_auditlog;
\dp auditlog_auditlog
```
Verified output:
```
ERROR:  permission denied for table auditlog_auditlog
ERROR:  permission denied for table auditlog_auditlog
 Schema |       Name        | Type  |         Access privileges
 public | auditlog_auditlog | table | evoting_user=arwdDxt/evoting_user+
        |                   |       | evoting_app=ar/evoting_user
```
Reading the flags: `a` INSERT, `r` SELECT — no `w` (UPDATE), `d` (DELETE) or `D` (TRUNCATE) for `evoting_app`. `has_table_privilege('evoting_app','auditlog_auditlog','UPDATE')` is `f`. The same restriction made `reset_demo` fail when run as this role.

### 5b. No link between ballots and voters
```
\d ballots_ballot
\d voters_voter
```
Verified: `ballots_ballot` has only `ballot_id, created_at, candidate_id, election_id`, with foreign keys to `elections_candidate` and `elections_election`; the only "Referenced by" is `auditlog_auditlog` (ballot → audit entry, one-way). `voters_voter` has `voter_id, national_id_hash, full_name, phone_number, otp_hash, registration_date, has_voted`; its "Referenced by" list is `voter_sessions_session` and `voters_voterelectionparticipation`. **Neither table references the other, and there is no ballot column in any voter-side table.**
Caution (from reading the code, not run): the participation row's `voted_at` and the ballot's `created_at` are written in the same transaction a few milliseconds apart, so someone with direct database access could try to correlate them by time. The schema contains no link; say "no structural link", not "impossible to correlate".

### 5c. National ID stored hashed
```
SELECT full_name, national_id_hash, length(national_id_hash) AS len FROM voters_voter ORDER BY registration_date LIMIT 3;
```
Verified: 64-hex-character SHA-256 values (e.g. `9711452…ecf58` for `39000001`), `len = 64`. `otp_hash` is also a hash and is empty after a successful login.

### 5d. Tamper detection — **RUN ONLY ON A COPY**

> **WARNING: never do this on the database you are presenting from, or on
> any database that matters.** It deliberately corrupts the audit chain.
> Work on a throwaway copy and drop it afterwards.

1. Stop `runserver` (a template database cannot have other connections), then copy:
   ```
   psql -h localhost -U evoting_user -d postgres -c "CREATE DATABASE evoting_demo_copy TEMPLATE evoting_dev;"
   ```
2. Start a second server on the copy:
   ```
   # bash:       DB_NAME=evoting_demo_copy python manage.py runserver 127.0.0.1:8766
   # PowerShell: $env:DB_NAME="evoting_demo_copy"; python manage.py runserver 127.0.0.1:8766
   ```
   Log in as `demo.auditor` (the copy contains the seeded users) → `/auditors/audit-log/verify/` → "Chain intact across all 7 entries" (verified).
3. Alter ONE hash **in the middle of the chain** as a role that may UPDATE (the table owner `evoting_user`, or a superuser such as `postgres`; a superuser bypasses grants entirely). Save the original first:
   ```
   psql -h localhost -U evoting_user -d evoting_demo_copy
   SELECT log_id, ballot_hash FROM auditlog_auditlog ORDER BY log_id;   -- note log_id N and its hash
   UPDATE auditlog_auditlog SET ballot_hash = repeat('0',64) WHERE log_id = N;
   ```
4. Reload `/auditors/audit-log/verify/`. *Verified result:*
   `Chain broken at log_id=N+1 (timestamp=…): expected previous_hash '0000…0000', found '<original hash>'…`
   (the break is reported at the **next** row, because each entry stores its predecessor's hash).
5. Restore:
   ```
   UPDATE auditlog_auditlog SET ballot_hash = '<original hash>' WHERE log_id = N;
   ```
   Reload → "Chain intact across all 7 entries" (verified).
6. Clean up: stop that server and `DROP DATABASE evoting_demo_copy;` (unset `DB_NAME`).

Limits to state honestly: choose a row that is **not the last** one (the walk checks each entry's `previous_hash` against its predecessor's `ballot_hash`; by its own description it is "a pure hash-chain walk over AuditLog's own columns", so altering the very last hash has no successor to disagree with — I reasoned this from the description, I did not run that case). The check does not recompute hashes from ballots. In my run the tamper was done as the table owner `evoting_user`, not as `postgres`; a superuser behaves the same because it ignores grants, but I did not run it as `postgres`.

---

## 6. FR-V-05 — is the token deleted or deactivated?

**Precisely: deactivated, not deleted.** In `ballots/services.py::cast_ballot`,
step 4 does `session.is_active = False; session.save(update_fields=["is_active"])`
inside the same `@transaction.atomic` block as the ballot write. The
`voter_sessions_session` row stays. The test is named accordingly:
`test_fr_v05_session_deactivated_not_deleted_after_cast`.

Verified live: after casting, the row has `is_active = f` and still exists (my
run: 10 session rows, 2 still active, all used ones `f`); replaying the same
token returns "Ballot Rejected"; the view also removes the token from the browser
session. Step 1 of `cast_ballot` only accepts a session that is `is_active=True`
and not expired, and returns the same message for "used", "expired" and
"never existed", so the token is unusable and cannot be told apart from a
nonexistent one.

**Why (the code's own comment):** `Session.is_active` exists to represent "this
token no longer works"; deactivation keeps a record that a session existed
without ever adding a Ballot→Session or Ballot→Voter reference. The anonymity
guarantee does not depend on the row: no ballot or audit field points at a
session, and the session row points only at the voter, so a retained inactive row
cannot reveal a choice.

**One correction to the code comment — don't repeat it to an examiner.** The
comment says the kept row is "an audit trail of which session cast which ballot".
It is not: nothing links a session to a ballot, so the row only shows that a voter
had a session that is now inactive.

**If an examiner asks "how does that satisfy *destroy*?"** — suggested answer:
> "REQUIREMENTS.md says destroy the token in the same atomic transaction as the
> ballot write. I interpreted destroy as *make the token permanently unusable*,
> not *physically remove the row*. The token is invalidated inside the same
> transaction, so it can never be committed half-way; after commit it cannot
> authenticate another ballot (I can show the replay being rejected and the row
> showing `is_active = false`). I kept the row because the model's `is_active`
> field exists for exactly that, and because it keeps an honest record that a
> session was used without linking it to any ballot. The anonymity property rests
> on the schema having no ballot-to-session link, not on the row being gone. If
> literal deletion is required, it is a one-line change (`session.delete()`) in
> that step plus an update to that one test, and I can discuss the trade-off."

Be prepared that "destroy" is a plain reading of delete; present this as a
documented design decision, not as the only possible reading. (This is a
decision for you and Ms. Siva; I have not changed it.)

---

## 7. What cannot be shown live, and the evidence to show instead

| Item | Why not live | Show instead |
|---|---|---|
| **TLS 1.3 (NFR-SE-01)** | The demo runs plain HTTP on `127.0.0.1`. Django does not terminate TLS; `config/settings/production.py` sets `SECURE_SSL_REDIRECT`, secure cookies, HSTS (1 year, subdomains, preload) and `SECURE_PROXY_SSL_HEADER`, but TLS 1.3 itself must be enforced by a reverse proxy/host. **The footer text "TLS 1.3" on pages is static text, visible even over HTTP — don't point at it as proof.** | `production.py`; the TLS section of `docs/SECURITY_TESTING_PLAN.md`; the Burp MITM plan. If you have a deployed host, `openssl s_client -connect host:443 -tls1_3` (not run; no deployment here). |
| Parameterised queries / SQLi (NFR-SE-01) | A negative result isn't a demo | Django ORM usage; the SQLMap plan in `docs/SECURITY_TESTING_PLAN.md`. I have not run SQLMap or Burp; the plan is a plan, not results. |
| MFA with a real SMS (FR-G-01) | Stub gateway; no real SMS provider | §3: the stub line and mock OTP; the `voters/sms_gateway.py` interface. |
| NFR-PE-01 Performance | Needs measurement over repeated requests | Run `curl -w "%{time_total}\n" -o /dev/null -s <url>` for login/cast/tally pages if you want numbers; I have not measured any. |
| NFR-US-01 Usability | Needs unassisted test users | The linear flow itself (§4.3); only cite user-test results if you actually have them. |
| NFR-AV-01 Availability | Needs a deployed, monitored window | Architecture description (app server + DB as the two failure points). |
| NFR-SC-01 Scalability | "Architectural provision only" (REQUIREMENTS §1.7) | `DATABASES` reads host/name from environment (`config/settings/base.py`): app and DB tiers are separately configurable. |
| NFR-MA-01 Maintainability | A property of the repo | The app layout (voters, ballots, elections, auditlog, tally, voter_sessions) and git history. |
| All of the above, as evidence | | `docs/TRACEABILITY.md` (requirement → test) and `pytest` (170 passed, 0 skipped with `DB_APP_PASSWORD` exported; the FR-DB-01 test silently skips if it is not). |

---

## 8. Quick troubleshooting
- OTP not on the page → `DJANGO_DEBUG` is not `True`.
- `seed_demo` says data already present → run `reset_demo --yes` first.
- `reset_demo` says "permission denied" → you are connected as `evoting_app`; use the owner credentials (`DB_USER`).
- `reset_demo` says audit rows belong to non-demo ballots → this is not a pure demo database; recreate it.
- Chooser not showing → fewer than two elections are OPEN.
- `CREATE DATABASE … TEMPLATE` fails "being accessed by other users" → stop every server/psql session on `evoting_dev`.

---

## 9. Not verified by running (read this before presenting)

*Added with FR-NAV-01 / FR-SES: only the staff login → Logout click path was checked in a real browser (and the nav bar's appearance on an Officials page). The Voter "End session" button, the "Session ended" and "Session expired" pages, and the absolute-timeout wait were exercised by automated tests and the Django test client only, not clicked in a browser; with the sandbox's blocked Tailwind CDN a browser screenshot of the full styling was not possible.*

I ran everything over HTTP and psql in a Linux sandbox. **Not verified:**

1. **Anything visual in a real browser** — layout, buttons, the Tailwind CDN needs internet. My checks were on HTTP responses and page text, not screenshots.
2. **Windows/PowerShell/psql-on-Windows commands** — written, not run; the sandbox is Linux/bash. psql was 16.x, not 15.
3. **Tamper demo as `postgres` (superuser)** — run as the owner `evoting_user`. Tampering with the *last* chain row — not run.
4. **Admin form submissions** — creating an election/candidates (FR-A-01/02): only the page load. The Officials-page Open/Close buttons — not clicked; their target (the admin action) was exercised. Adding a candidate through the standalone Candidate admin to an OPEN election — not run.
5. **Dual-role chooser** `/post-login/choose/` — not run live (only code read).
6. **Confirmation-receipt hash equals the audit-log row's hash** — not compared by eye.
7. **OTP expiry (5 min) and token expiry (15 min)** — not waited out; covered by existing tests only.
8. **Concurrent/double-submit races** — not exercised live.
9. **Your machine** — your `.env`, role password and seeded state may differ; I did not run the seed on it. The full suite passed (159) in the sandbox after adding these commands; I did not re-run it on your machine.
10. **The two new management commands have no tests of their own** (you asked me not to edit tests, and I added none).
11. **Privacy-notice wording about the application log** — found inaccurate for the default settings (§3); not changed.
