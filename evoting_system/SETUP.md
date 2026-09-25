# SETUP.md — Local Development Setup

Sprint 1 scope only: this gets the project running with the six
models, Django admin CRUD for FR-A-01/FR-A-02, an empty DRF router,
and a placeholder home page. No auth, ballot casting, or tally code
exists yet — see CLAUDE.md for the sprint roadmap.

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
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL connection |

`config/settings/base.py` reads all of these via `python-decouple` —
nothing environment-specific is hardcoded in settings.

## 3. Create the PostgreSQL database

```bash
sudo -u postgres psql -c "CREATE USER evoting_user WITH PASSWORD 'yourpassword' CREATEDB;"
sudo -u postgres psql -c "CREATE DATABASE evoting_dev OWNER evoting_user;"
```

Match these to whatever you put in `.env`.

## 4. Run migrations

```bash
python manage.py migrate
```

This creates all six tables (`Voter`, `Session`, `Ballot`, `Candidate`,
`Election`, `AuditLog`) with exactly the fields in `SCHEMA.md`, and
confirms there is no foreign key from `Ballot` to `Voter` or `Session`
anywhere in the schema (verified manually against `pg_constraint`
during this sprint's build — see handover).

## 5. Create an admin user

```bash
python manage.py createsuperuser
```

Log into `/admin/` to exercise FR-A-01 (create an Election) and
FR-A-02 (add Candidates, via the inline on the Election page).

## 6. Run the dev server

```bash
python manage.py runserver
```

- `/` — placeholder home page
- `/admin/` — Django admin (Election/Candidate CRUD)
- `/api/` — empty DRF router (returns 403 to anonymous requests by
  design — `DEFAULT_PERMISSION_CLASSES` is `IsAdminUser` and there are
  no endpoints registered yet)

## 7. Run tests

```bash
pytest
```

Runs the one smoke test per model (creation only — not real FR/NFR
coverage; see `REQUIREMENTS.md` §8 for the full testing strategy that
later sprints build toward). Tests run against the real PostgreSQL
database configured in `.env` (no sqlite anywhere), so steps 2–3 above
must be done first.

## Known TODOs carried into later sprints

- **FR-A-03 / FR-A-04** (open/close voting period; lock candidates once
  voting opens): stubbed as comments in `elections/admin.py` and
  `elections/models.py`. Not implemented.
- **FR-DB-01** (insert-only `AuditLog` at the PostgreSQL role level):
  the `AuditLog` model exists, but no `GRANT`/`REVOKE` has been applied
  to the application's DB role yet. Until that lands, the app's DB user
  can UPDATE/DELETE `AuditLog` rows like any other table — do not treat
  this as done. Recommended approach when implemented: a migration
  that runs `REVOKE UPDATE, DELETE ON auditlog_auditlog FROM <app_role>;`
  as raw SQL, plus a dedicated, more restricted DB role for the app to
  connect as in production.
- Authentication, OTP/MFA, the SMS gateway client, session token
  issuance/destruction, the ballot-casting transaction, SHA-256
  hashing, and ZKP/tally code are all out of scope until Sprints 2–4.
