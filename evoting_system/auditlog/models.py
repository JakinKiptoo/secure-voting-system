from django.db import models

from ballots.models import Ballot


class AuditLog(models.Model):
    """
    Audit Log Module -- SCHEMA.md "AuditLog".

    Insert-only at the PostgreSQL role level (FR-DB-01, CLAUDE.md #3):
    UPDATE/DELETE must be blocked by a Postgres GRANT/REVOKE on the
    application's DB role, not by Django model restrictions -- that
    configuration is explicitly out of Sprint 1 scope (see SETUP.md
    TODO) and belongs with the rest of the security-hardening work in
    Sprint 3/5. Nothing below should be read as enforcing insert-only
    behaviour; it doesn't yet.

    `ballot` (OneToOneField, on_delete=PROTECT) resolves the ambiguity
    flagged during Sprint 1: SCHEMA.md's original field list omitted a
    foreign key back to Ballot even though the class diagram (S4.5.2)
    and ERD (S4.5.5) both show a 1--1 Ballot<->AuditLog relationship.
    The updated SCHEMA.md adds it explicitly, on the AuditLog side (as
    Sprint 1 already reasoned it should live, to keep Ballot free of
    anything resembling a voter-identifying reference). PROTECT so a
    Ballot can never be deleted out from under its audit trail.
    """

    log_id = models.BigAutoField(primary_key=True)
    ballot = models.OneToOneField(
        Ballot,
        on_delete=models.PROTECT,
        related_name="audit_log",
        db_column="ballot_id",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    action_type = models.CharField(max_length=100)
    ballot_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="SHA-256 hex digest, generated under FR-V-07 (Sprint 3).",
    )
    previous_hash = models.CharField(
        max_length=64,
        blank=True,
        help_text="Chains entries so the sequence itself is verifiable.",
    )

    class Meta:
        verbose_name = "Audit Log Entry"
        verbose_name_plural = "Audit Log Entries"

    def __str__(self):
        return f"AuditLog {self.log_id} ({self.action_type})"


class AuthSecurityEvent(models.Model):
    """
    FR-SES-04 (EXTENSIONS_ROADMAP.md): insert-only record of
    authentication security events -- currently only 'otp_lockout'.

    Deliberately separate from AuditLog: AuditLog rows are the ballot
    hash chain (one per Ballot) read by Verify chain and the public
    tally, and a non-ballot row there would break that chain.

    Holds id, timestamp and event_type ONLY. No voter, session, National
    ID, phone number, OTP or IP address, and no foreign key to Ballot,
    Voter or Session: an event records THAT a lockout happened, never
    WHO was locked out. Insert-only for the restricted runtime role via
    scripts/setup_db_roles.sql (same GRANT/REVOKE pattern as AuditLog).
    """

    OTP_LOCKOUT = "otp_lockout"

    id = models.BigAutoField(primary_key=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    event_type = models.CharField(max_length=50)

    class Meta:
        verbose_name = "Authentication Security Event"
        verbose_name_plural = "Authentication Security Events"

    def __str__(self):
        return f"AuthSecurityEvent {self.id} ({self.event_type})"
