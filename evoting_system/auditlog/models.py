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
