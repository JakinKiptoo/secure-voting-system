import uuid

from django.db import models


class Election(models.Model):
    """Election Administration Module -- SCHEMA.md "Election"."""

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
            "Open/close lifecycle state, per the updated SCHEMA.md "
            "(DRAFT/OPEN/CLOSED enum). FR-A-03 (open/close a voting "
            "period, reject ballots outside it) and FR-A-04 (lock "
            "candidates once OPEN) are still NOT implemented -- the "
            "value is now constrained to these three states, but "
            "nothing yet enforces transitions or acts on them. See "
            "elections/admin.py TODO for the Sprint-2+ stub."
        ),
    )

    class Meta:
        verbose_name = "Election"
        verbose_name_plural = "Elections"

    def __str__(self):
        return self.title


class Candidate(models.Model):
    """Election Administration Module -- SCHEMA.md "Candidate"."""

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
