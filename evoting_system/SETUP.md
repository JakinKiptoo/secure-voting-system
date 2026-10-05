# SETUP.md — Local Development Setup

Covers Sprints 1–3: the six models, Django admin CRUD for FR-A-01 to
FR-A-04, the Voter Authentication Module (FR-V-00 to FR-V-03, FR-S-01,
FR-G-01), and the Ballot Casting Module including the insert-only
AuditLog role (FR-V-04 to FR-V-08, FR-DB-01). No ZKP, tally, or public
verification endpoint yet — see CLAUDE.md for the sprint roadmap.

## Prerequisites

- Python 3.11 (project targets 3.11; developed/verified here on 3.12,
  which is compatible with Django 4.2 — switch to 3.11 if you want an
  exact match with REQUIREMENTS.md §3)
- PostgreSQL 15
- `pip`

## 1. Clone and create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Configure environment variables

Copy `.env.example` to `.env` and fill in real values:

```bash
cp .env.example .env
```

| Variable | Purpose |
|---|---|
| `DJANGO_SETTINGS_MODULE` | `config.settings.local` for dev, `config.settings.production` for prod |
| `DJANGO_SECRET_KEY` | Django secret key — generate a real random value, never reuse the example |
| `DJANGO_DEBUG` | `True` locally, must be unset/`False` in production |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames; required (non-empty) in production |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection Django itself uses (`DATABASES`) |
| `DB_APP_USER`, `DB_APP_PASSWORD` | **Not read by Django.** Only used by `auditlog/tests.py::test_fr_db01_auditlog_insert_only_at_role_level` to open a *separate* raw connection as the restricted `evoting_app` role and prove FR-DB-01 actually holds. See step 6. |

`config/settings/base.py` reads the `DB_*` (non-`APP`) variables via
`python-decouple` — nothing environment-specific is hardcoded in
settings.

## 3. Create the PostgreSQL database

```bash
sudo -u postgres psql -c "CREATE USER evoting_user WITH PASSWORD 'yourpassword' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE evoting_dev OWNER evoting_user;"
```

Match these to `DB_USER`/`DB_PASSWORD`/`DB_NAME` in `.env`. This is
the **migration/owner role** — see step 6 for why it must stay
separate from the app's day-to-day runtime role.

## 4. Run migrations

```bash
python manage.py migrate
```

Creates all six tables with exactly the fields in `SCHEMA.md`; no FK
from `Ballot` to `Voter` or `Session` anywhere (verified manually
against `pg_constraint`); `AuditLog.ballot` is a `OneToOneField` to
`Ballot` (added in the pre-Sprint-2 correction); `Voter.national_id_hash`
is `unique=True` at the DB level (added in the pre-Sprint-3
correction).

## 5. Create an admin user

```bash
python manage.py createsuperuser
```

Log into `/admin/` to:
- FR-A-01/FR-A-02: create an Election, add Candidates (inline).
- FR-A-03: select an Election and run the **"Open selected elections
  for voting"** / **"Close selected elections"** actions from the
  admin list view's Actions dropdown — don't edit the `status` field
  directly; the actions enforce the DRAFT → OPEN → CLOSED order.
- FR-A-04: once an Election is no longer DRAFT, its candidate inline
  becomes read-only (add/change/delete all disabled) — this is also
  enforced at the model layer (`Candidate.clean()`/`save()`), not just
  in the admin UI.

## 6. Configure the insert-only AuditLog role (FR-DB-01)

**Do this after step 4** (the tables must already exist):

```bash
sudo -u postgres psql -d evoting_dev -f scripts/setup_db_roles.sql
```

Edit the password in that script first (or `ALTER ROLE evoting_app
WITH PASSWORD '...'` immediately after running it). This creates a
second, restricted `evoting_app` role with full CRUD on every table
**except** `AuditLog`, where it only has `SELECT`/`INSERT` — `UPDATE`
and `DELETE` are revoked. Full rationale and a manual `SET ROLE`
verification recipe are in the script's own comments.

Two roles, two purposes, don't mix them up:
- **`evoting_user`** (from step 3) — owns every table. Table owners
  bypass `GRANT`/`REVOKE` in PostgreSQL, so this role must keep
  running `migrate` and local `pytest` runs, but should **never** be
  what a live application connects as.
- **`evoting_app`** (from this step) — the role a *deployed* app
  should actually use for `DATABASES`/`DB_USER` in
  `config/settings/production.py`'s environment. Locally, keep
  `DB_USER=evoting_user` in `.env` so `migrate` and `pytest` keep
  working — `pytest-django` needs `CREATEDB`-level privileges to spin
  up a throwaway test database, which `evoting_app` deliberately
  lacks.

To actually exercise the restriction from the test suite, add to
`.env` (or export in your shell):

```
DB_APP_USER=evoting_app
DB_APP_PASSWORD=<the password you set above>
```

`auditlog/tests.py::test_fr_db01_auditlog_insert_only_at_role_level`
opens its own raw `psycopg2` connection as this role (separate from
Django's own `evoting_user` connection) and confirms `UPDATE`/`DELETE`
against `auditlog_auditlog` both fail with "permission denied". If
`DB_APP_PASSWORD` isn't set, or the role isn't reachable, this one
test is **skipped** (not failed) — the rest of the suite doesn't
depend on this step having been done.

## 7. Run the dev server

```bash
python manage.py runserver
```

- `/` — home page, links to registration and login
- `/voters/register/`, `/voters/login/`, `/voters/verify-otp/` — FR-V-00 to FR-V-03, FR-S-01, FR-G-01
- `/ballots/cast/` — FR-V-04 to FR-V-08 (requires an active session token from `/voters/`, and at least one `OPEN` Election)
- `/admin/` — Django admin
- `/api/` — empty DRF router (returns 403 to anonymous requests by
  design — `DEFAULT_PERMISSION_CLASSES` is `IsAdminUser` and there are
  no endpoints registered yet)

With `DJANGO_DEBUG=True`, the OTP verification page also shows the
mock OTP value on-screen (clearly labeled, DEBUG-only) since the stub
SMS gateway only logs it and Django's default logging config drops
that log line silently — see `voters/views.py` docstring.

## 8. Run tests

```bash
pytest
```

26 tests as of Sprint 3 (see `REQUIREMENTS.md` §8 for the full
testing strategy Sprint 5 builds toward — this is functional
correctness coverage, not the security/compliance pass). Tests run
against the real PostgreSQL database configured in `.env` (no sqlite
anywhere), so steps 2–3 above must be done first; step 6 is only
needed for the one FR-DB-01 test to run instead of skip.

## Known TODOs carried into later sprints

- **ZKP generation, tally computation, public verification endpoint**
  (FR-V-08's receipt only covers the ballot-casting confirmation, not
  the public tally side of things) — Sprint 4.
- **Prior-session invalidation**: a voter who logs in twice (Sprint 2)
  ends up with two active `Session` rows; `cast_ballot()` defends
  against a resulting double-vote with a `has_voted` re-check
  (`ballots/services.py`), but the stale second `Session` itself is
  never cleaned up. Not a correctness bug given the re-check, but
  worth a look.
- **FR-A-04 enforcement is model-layer, not a DB trigger/constraint**
  — a deliberate scope choice (see `elections/models.py` Candidate
  docstring), lighter than FR-DB-01's DB-role guarantee. Revisit if a
  genuine DB-level lock is wanted.
- **`scripts/setup_db_roles.sql` has no `ALTER DEFAULT PRIVILEGES`** —
  if a later sprint adds new tables, re-run its `GRANT ... ALL TABLES`
  lines so `evoting_app` can see them.
- Pytest-Django's security/compliance pass (Burp Suite, SQLMap,
  DPA-2019 checklist) is Sprint 5, not done here.
