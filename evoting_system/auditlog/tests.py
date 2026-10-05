import os
from datetime import timedelta

import psycopg2
import pytest
from django.utils import timezone

from ballots.models import Ballot
from elections.models import Candidate, Election

from .models import AuditLog


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

    Requires scripts/setup_db_roles.sql to have been run against this
    database, and DB_APP_USER/DB_APP_PASSWORD to be set in the
    environment (see SETUP.md) -- skipped, not failed, if either
    precondition isn't met, so the rest of the suite doesn't depend on
    that one-time DB setup step having happened.
    """
    app_user = os.environ.get("DB_APP_USER", "evoting_app")
    app_password = os.environ.get("DB_APP_PASSWORD")
    db_name = os.environ.get("DB_NAME", "evoting_dev")
    db_host = os.environ.get("DB_HOST", "localhost")
    db_port = os.environ.get("DB_PORT", "5432")

    if not app_password:
        pytest.skip(
            "DB_APP_PASSWORD not set -- run scripts/setup_db_roles.sql and "
            "set DB_APP_USER/DB_APP_PASSWORD to exercise FR-DB-01 directly."
        )

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
        conn = psycopg2.connect(
            dbname=db_name,
            user=app_user,
            password=app_password,
            host=db_host,
            port=db_port,
        )
    except psycopg2.OperationalError as exc:
        pytest.skip(
            f"Could not connect as {app_user!r} ({exc}); run "
            "scripts/setup_db_roles.sql against this database first."
        )

    try:
        conn.autocommit = True

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
