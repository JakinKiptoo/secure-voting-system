# Sprint 1 correction: add AuditLog.ballot as a OneToOneField to
# Ballot (on_delete=PROTECT), per the updated SCHEMA.md. Resolves the
# FK-side ambiguity flagged during Sprint 1's original build (see
# auditlog/models.py docstring). No existing AuditLog rows exist yet
# in any environment that has only run through Sprint 1, so no data
# backfill is required.

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('auditlog', '0001_initial'),
        ('ballots', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='auditlog',
            name='ballot',
            field=models.OneToOneField(
                db_column='ballot_id',
                on_delete=django.db.models.deletion.PROTECT,
                related_name='audit_log',
                to='ballots.ballot',
                # No default: this is a required 1--1 link going
                # forward. If you are applying this migration against
                # an environment that already has AuditLog rows (it
                # shouldn't, at Sprint 1), backfill them before
                # running migrate, or the ADD COLUMN ... NOT NULL will
                # fail against Postgres.
                null=False,
            ),
            preserve_default=False,
        ),
    ]
