import os
import re
from datetime import timedelta
from pathlib import Path

import psycopg2
import psycopg2.sql
import pytest
from django.conf import settings
from django.db import connection
from django.utils import timezone

from ballots.models import Ballot
from elections.models import Candidate, Election

from .models import AuditLog, AuthSecurityEvent

SETUP_DB_ROLES_SQL = Path(settings.BASE_DIR) / "scripts" / "setup_db_roles.sql"


def _restricted_role_connection():
    """
    Raw autocommit psycopg2 connection as the restricted runtime role
    (DB_APP_USER, default evoting_app) to the SAME database the suite
    is using (Django's connection settings: the pytest test database,
    DB_HOST, DB_PORT). Applies scripts/setup_db_roles.sql to that
    database first, through Django's owner connection. Skips only if
    DB_APP_PASSWORD is unset or the role cannot connect.
    """
    app_user = os.environ.get("DB_APP_USER", "evoting_app")
    app_password = os.environ.get("DB_APP_PASSWORD")
    if not app_password:
        pytest.skip(
            "DB_APP_PASSWORD not set -- run scripts/setup_db_roles.sql and "
            "set DB_APP_USER/DB_APP_PASSWORD to exercise the role-level checks."
        )

    db = connection.settings_dict
    try:
        conn = psycopg2.connect(
            dbname=db["NAME"],
            user=app_user,
            password=app_password,
            host=db["HOST"] or "localhost",
            port=db["PORT"] or "5432",
        )
    except psycopg2.OperationalError as exc:
        pytest.skip(f"Could not connect as {app_user!r} to {db['NAME']!r} ({exc}).")
    conn.autocommit = True

    # Role exists (we just connected as it), so the script's CREATE ROLE
    # block is a no-op; only its GRANT/REVOKE lines take effect.
    with connection.cursor() as cur:
        cur.execute(_roles_sql_for_cursor(app_password, conn))
    return conn


def _roles_sql_for_cursor(app_password, raw_conn):
    """
    scripts/setup_db_roles.sql is written for psql: it takes the
    evoting_app password from the psql variable app_password and has a
    psql-only \\if guard for when that variable is missing. Running it
    through a database cursor instead, drop that guard block and put
    the DB_APP_PASSWORD value in as a properly quoted SQL literal.
    The GRANT/REVOKE statements are run exactly as written.
    """
    text = SETUP_DB_ROLES_SQL.read_text(encoding="utf-8")
    text, guards = re.subn(r"(?ms)^\\if\b.*?^\\endif[^\n]*\n", "", text)
    assert guards == 1, "expected exactly one \\if ... \\endif guard in setup_db_roles.sql"
    assert ":'app_password'" in text, "setup_db_roles.sql no longer uses the app_password variable"
    return text.replace(":'app_password'", psycopg2.sql.Literal(app_password).as_string(raw_conn))


@pytest.mark.django_db
def test_auditlog_creation():
    """
    Smoke test only (Sprint 1, updated after the AuditLog.ballot
    correction): confirms AuditLog can be created with the fields
    SCHEMA.md lists, including the required OneToOneField to Ballot.
    Does NOT test insert-only enforcement (FR-DB-01) -- that's a
    PostgreSQL role-level GRANT/REVOKE, not application code, and is
    out of Sprint 1 scope.
    """
    now = timezone.now()
    election = Election.objects.create(
        title="2027 Student Council Election",
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    candidate = Candidate.objects.create(election=election, name="Amina Yusuf")
    ballot = Ballot.objects.create(election=election, candidate=candidate)

    entry = AuditLog.objects.create(
        ballot=ballot,
        action_type="ballot_cast",
        ballot_hash="0" * 64,
        previous_hash="",
    )

    assert entry.log_id is not None
    assert entry.timestamp is not None
    assert entry.ballot == ballot


@pytest.mark.django_db(transaction=True)
def test_fr_db01_auditlog_insert_only_at_role_level():
    """
    FR-DB-01 (Sprint 3): AuditLog is insert-only at the PostgreSQL
    role level, independent of application code.

    This does NOT go through Django's ORM/default connection at all
    for the actual check -- that connection uses whatever DB_USER is
    configured (normally the migration/owner role, which as table
    owner always bypasses GRANT/REVOKE and would make this test
    meaningless). Instead it opens a SEPARATE raw psycopg2 connection
    authenticated as the restricted `evoting_app` role created by
    scripts/setup_db_roles.sql, and confirms THAT connection gets
    "permission denied" on both UPDATE and DELETE against
    auditlog_auditlog.

    Uses `django_db(transaction=True)` (real commits, not the usual
    per-test rollback) so the row created via the normal Django
    connection is actually visible to the separate raw connection --
    two different Postgres sessions can't see each other's
    uncommitted work.

    Database target (security-run finding F3): the raw connection uses
    Django's own connection settings -- the same test database, host
    and port as the rest of the suite -- not os.environ with a
    hard-coded evoting_dev/5432 default. Because that test database is
    created fresh by pytest, the test applies scripts/setup_db_roles.sql
    to it first (as the owner connection), so what is checked is the
    real script's GRANT/REVOKE on the real migrated schema. A positive
    SELECT as the restricted role proves the grants were applied and
    the row is visible, so the denials cannot come from "no grants at
    all".

    Requires the evoting_app role to exist on the server and
    DB_APP_USER/DB_APP_PASSWORD in the environment (see SETUP.md) --
    skipped, not failed, only if DB_APP_PASSWORD is unset or the role
    cannot connect.
    """
    conn = _restricted_role_connection()

    now = timezone.now()
    election = Election.objects.create(
        title="2027 Student Council Election",
        start_date=now,
        end_date=now + timedelta(days=1),
    )
    candidate = Candidate.objects.create(election=election, name="Amina Yusuf")
    ballot = Ballot.objects.create(election=election, candidate=candidate)
    entry = AuditLog.objects.create(
        ballot=ballot,
        action_type="ballot_cast",
        ballot_hash="c" * 64,
        previous_hash="",
    )

    try:
        # Positive control: the restricted role can read the row.
        with conn.cursor() as cur:
            cur.execute("SELECT action_type FROM auditlog_auditlog WHERE log_id = %s", [entry.log_id])
            assert cur.fetchone() == ("ballot_cast",)

        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error) as update_exc:
                cur.execute(
                    "UPDATE auditlog_auditlog SET action_type = %s WHERE log_id = %s",
                    ["tampered", entry.log_id],
                )
        assert "permission denied" in str(update_exc.value).lower()

        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error) as delete_exc:
                cur.execute(
                    "DELETE FROM auditlog_auditlog WHERE log_id = %s", [entry.log_id]
                )
        assert "permission denied" in str(delete_exc.value).lower()
    finally:
        conn.close()

    # Neither statement should have taken effect.
    entry.refresh_from_db()
    assert entry.action_type == "ballot_cast"
    assert AuditLog.objects.filter(pk=entry.pk).exists()


@pytest.mark.django_db(transaction=True)
def test_fr_ses04_security_event_insert_only_at_role_level():
    """
    FR-SES-04: auditlog_authsecurityevent is insert-only for the
    restricted role, same GRANT/REVOKE pattern and same database target
    as the FR-DB-01 test above. Skipped only if DB_APP_PASSWORD is unset
    (or the role cannot connect).
    """
    conn = _restricted_role_connection()
    event = AuthSecurityEvent.objects.create(event_type=AuthSecurityEvent.OTP_LOCKOUT)
    try:
        # Positive control: INSERT and SELECT are allowed.
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO auditlog_authsecurityevent (timestamp, event_type) VALUES (now(), %s)",
                ["otp_lockout"],
            )
            cur.execute("SELECT event_type FROM auditlog_authsecurityevent WHERE id = %s", [event.id])
            assert cur.fetchone() == ("otp_lockout",)

        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error) as update_exc:
                cur.execute(
                    "UPDATE auditlog_authsecurityevent SET event_type = %s WHERE id = %s",
                    ["tampered", event.id],
                )
        assert "permission denied" in str(update_exc.value).lower()

        with conn.cursor() as cur:
            with pytest.raises(psycopg2.Error) as delete_exc:
                cur.execute("DELETE FROM auditlog_authsecurityevent WHERE id = %s", [event.id])
        assert "permission denied" in str(delete_exc.value).lower()
    finally:
        conn.close()

    event.refresh_from_db()
    assert event.event_type == "otp_lockout"
    assert AuthSecurityEvent.objects.count() == 2
