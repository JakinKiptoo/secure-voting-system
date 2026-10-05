import uuid

from django.db import models


class Voter(models.Model):
    """
    Voter Authentication Module -- SCHEMA.md "Voter".

    Non-negotiable design invariant (CLAUDE.md #1, REQUIREMENTS.md S5):
    this model holds NO attribute or relationship referencing any
    Ballot instance, directly or indirectly. Anonymisation is enforced
    structurally by the absence of that field, not by convention. Do
    not add a `ballot` / `ballots` field here under any circumstances.
    """

    voter_id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    national_id_hash = models.CharField(
        max_length=255,
        unique=True,
        help_text=(
            "Hashed National ID -- the raw National ID is never stored. "
            "unique=True enforces FR-V-00's uniqueness requirement at "
            "the database level (Sprint 3 correction): the application-"
            "layer check in VoterRegistrationForm.clean_national_id "
            "alone can't stop two concurrent registration requests for "
            "the same National ID both passing validation before either "
            "commits -- the DB constraint is what actually closes that "
            "race."
        ),
    )
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20)
    otp_hash = models.CharField(
        max_length=255,
        blank=True,
        help_text="Hashed OTP secret. Populated by the MFA pipeline (Sprint 2, FR-V-03).",
    )
    registration_date = models.DateTimeField(
        auto_now_add=True,
        help_text="Set under FR-V-00 at registration time.",
    )
    has_voted = models.BooleanField(
        default=False,
        help_text="Checked at authentication under FR-V-02.",
    )

    class Meta:
        verbose_name = "Voter"
        verbose_name_plural = "Voters"

    def __str__(self):
        return f"Voter {self.voter_id}"
