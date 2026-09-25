# Sprint 1 correction: Election.status -> TextChoices (DRAFT/OPEN/CLOSED),
# per the updated SCHEMA.md. Schema-only change (max_length, choices,
# default) -- no data migration needed since no elections exist yet
# outside local dev/test data.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('elections', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='election',
            name='status',
            field=models.CharField(
                choices=[('DRAFT', 'Draft'), ('OPEN', 'Open'), ('CLOSED', 'Closed')],
                default='DRAFT',
                help_text=(
                    'Open/close lifecycle state, per the updated SCHEMA.md '
                    '(DRAFT/OPEN/CLOSED enum). FR-A-03 (open/close a voting '
                    'period, reject ballots outside it) and FR-A-04 (lock '
                    'candidates once OPEN) are still NOT implemented -- the '
                    'value is now constrained to these three states, but '
                    'nothing yet enforces transitions or acts on them. See '
                    'elections/admin.py TODO for the Sprint-2+ stub.'
                ),
                max_length=10,
            ),
        ),
    ]
