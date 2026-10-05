import uuid

from django.core.exceptions import ValidationError
from django.db import models


class Election(models.Model):
    """
    Election Administration Module -- SCHEMA.md "Election".

    Sprint 3: FR-A-03 (open/close a voting period) is implemented via
    open_voting()/close_voting(), which enforce the only two legal
    transitions (DRAFT -> OPEN -> CLOSED, no skipping, no reversal).
    The ballots app's cast_ballot() (FR-A-03's other half: reject
    ballots submitted outside an open period) checks `status ==
    Election.Status.OPEN` before recording anything.
    """

    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        OPEN = "OPEN", "Open"
        CLOSED = "CLOSED", "Closed"

    election_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.DRAFT,
        help_text=(
            "Open/close lifecycle state (DRAFT/OPEN/CLOSED). Use "
            "open_voting()/close_voting() to transition rather than "
            "setting this field directly, so the only-forward-one-step "
            "rule (FR-A-03) is enforced."
        ),
    )

    class Meta:
        verbose_name = "Election"
        verbose_name_plural = "Elections"

    def __str__(self):
        return self.title

    def open_voting(self):
        """FR-A-03: open a DRAFT election for voting. DRAFT -> OPEN only."""
        if self.status != self.Status.DRAFT:
            raise ValidationError(
                f"Cannot open '{self}': only a DRAFT election can be opened "
                f"(current status: {self.get_status_display()})."
            )
        self.status = self.Status.OPEN
        self.save(update_fields=["status"])

    def close_voting(self):
        """FR-A-03: close an OPEN election. OPEN -> CLOSED only."""
        if self.status != self.Status.OPEN:
            raise ValidationError(
                f"Cannot close '{self}': only an OPEN election can be closed "
                f"(current status: {self.get_status_display()})."
            )
        self.status = self.Status.CLOSED
        self.save(update_fields=["status"])


class Candidate(models.Model):
    """
    Election Administration Module -- SCHEMA.md "Candidate".

    Sprint 3: FR-A-04 (block candidate additions/modifications once
    voting has opened) is enforced in clean(), which both
    ModelAdmin/ModelForm validation AND save() (below) invoke -- so it
    holds for admin edits *and* direct ORM/shell usage, not only the
    admin UI. It does NOT hold against QuerySet.update()/bulk
    operations, which bypass save()/clean() entirely; that's a known
    Django limitation, not something this override can close, and
    admin CRUD (the only Candidate-writing path built so far) never
    uses those. This is model-layer enforcement, not a PostgreSQL
    trigger/constraint -- a lighter guarantee than FR-DB-01's DB-role
    enforcement for AuditLog. Flagged as a deliberate scope choice:
    implementing a real DB trigger for this was judged disproportionate
    given nothing outside Django admin writes Candidate rows yet.
    """

    candidate_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    election = models.ForeignKey(
        Election,
        on_delete=models.CASCADE,
        related_name="candidates",
        db_column="election_id",
    )
    name = models.CharField(max_length=255)
    party = models.CharField(max_length=255, blank=True)
    biography = models.TextField(blank=True)

    class Meta:
        verbose_name = "Candidate"
        verbose_name_plural = "Candidates"

    def __str__(self):
        return f"{self.name} ({self.party})" if self.party else self.name

    def clean(self):
        super().clean()
        if self.election_id and self.election.status != Election.Status.DRAFT:
            raise ValidationError(
                "Candidates cannot be added or modified once voting has "
                "opened (FR-A-04)."
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)
