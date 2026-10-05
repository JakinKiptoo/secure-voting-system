-- scripts/setup_db_roles.sql
--
-- FR-DB-01 (REQUIREMENTS.md; CLAUDE.md #3): AuditLog is insert-only
-- at the PostgreSQL role level, independent of application code --
-- this must hold even if the Django application layer is fully
-- compromised. That can't be done inside a Django migration, because
-- migrations run using the SAME role the app is configured to use
-- (DATABASES in config/settings), and PostgreSQL table OWNERS always
-- bypass GRANT/REVOKE restrictions on their own tables regardless of
-- what's revoked. So the role that owns the tables can never be the
-- role this restriction is enforced against.
--
-- This script therefore introduces a SECOND, deliberately weaker
-- role for the application to actually connect as day-to-day:
--   - MIGRATION / OWNER role (whatever DB_USER you already used for
--     `python manage.py migrate` -- e.g. evoting_user): owns every
--     table. Keep using it for migrations. Never point a running
--     application at it.
--   - RUNTIME role (evoting_app, created below): what the Django app
--     should actually connect as (DATABASES / DB_USER) once this has
--     been run. Full CRUD everywhere except AuditLog, where it's
--     insert/select only.
--
-- Run this ONCE, as a PostgreSQL superuser, AFTER `migrate` has
-- already created the schema (so `ALL TABLES IN SCHEMA public`
-- below actually has something to grant against):
--
--   sudo -u postgres psql -d evoting_dev -f scripts/setup_db_roles.sql
--
-- CHANGE THE PASSWORD BELOW before running this anywhere but a local
-- throwaway dev database, then rotate it via ALTER ROLE immediately
-- after for anything resembling production.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'evoting_app') THEN
        CREATE ROLE evoting_app WITH LOGIN PASSWORD 'change-me-before-running';
    END IF;
END
$$;

GRANT USAGE ON SCHEMA public TO evoting_app;

-- Ordinary CRUD everywhere -- the app needs to read/write Voter,
-- Session, Ballot, Election, Candidate freely.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO evoting_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO evoting_app;

-- FR-DB-01: narrow AuditLog specifically to insert-only. The GRANT
-- re-states SELECT/INSERT (redundant after the broad grant above,
-- but keeps this block self-documenting and correct even if run
-- standalone later); the REVOKE is what actually removes UPDATE/
-- DELETE that the broad grant above just gave it.
GRANT SELECT, INSERT ON auditlog_auditlog TO evoting_app;
REVOKE UPDATE, DELETE ON auditlog_auditlog FROM evoting_app;

-- Verification (run manually against this same database, as the
-- postgres superuser or the owner role -- NOT as evoting_app, since
-- SET ROLE itself requires membership/superuser to invoke):
--
--   SET ROLE evoting_app;
--   UPDATE auditlog_auditlog SET action_type = 'tampered';  -- expect: permission denied
--   DELETE FROM auditlog_auditlog;                          -- expect: permission denied
--   RESET ROLE;
--
-- Sprint 3's automated test (auditlog/tests.py::
-- test_fr_db01_auditlog_insert_only_at_role_level) does the same
-- check programmatically, over a separate raw connection
-- authenticated as evoting_app -- see that test's docstring and
-- SETUP.md for the DB_APP_USER/DB_APP_PASSWORD it needs.
--
-- NOTE: if a later sprint adds new tables via further migrations,
-- re-run (at least) the two "GRANT ... ALL TABLES" lines above so
-- evoting_app can see them -- this script does not set up
-- ALTER DEFAULT PRIVILEGES for future tables, to keep it simple and
-- explicit for a proof-of-concept project.
