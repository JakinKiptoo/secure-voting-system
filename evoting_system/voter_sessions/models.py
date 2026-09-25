import uuid

from django.db import models

from voters.models import Voter


class Session(models.Model):
    """
    Session Management Module -- SCHEMA.md "Session".

    Valid only for the lifetime of the active session (FR-S-01); the
    record is invalidated once the session ends. Per SCHEMA.md's
    closing note, the "transient relationship to Ballot" described in
    the ERD is intentionally NOT modelled as a persisted field here --
    most ORMs (Django included) can't declaratively express "a
    relationship that deletes itself", so in practice the UUID token
    is passed through the view/service layer only at submission time
    (Sprint 3) and Ballot never gets a `session` field.

    Token issuance (FR-S-01) and destruction (FR-V-05) are Sprint 2/3
    behaviour -- this model only provides the storage shape.
    """

    session_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    voter = models.ForeignKey(
        Voter,
        on_delete=models.CASCADE,
        related_name="sessions",
        db_column="voter_id",
    )
    uuid_token = models.UUIDField(
        unique=True,
        default=uuid.uuid4,
        help_text="Single-use session-bound token (FR-V-03 / FR-S-01).",
    )
    expiry_time = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Session"
        verbose_name_plural = "Sessions"

    def __str__(self):
        return f"Session {self.session_id} (active={self.is_active})"
