# Data migration: creates the "Official" Group (FR-OFF-01) so it
# exists out of the box rather than requiring a manual setup step.
# Depends on auth's initial migration specifically because that's the
# migration that creates the Group table this RunPython writes to --
# not because officials has any model relationship with auth.
#
# reverse_code is intentionally migrations.RunPython.noop: unmigrating
# this app should not delete the group and silently strip every
# Official's role membership along with it.

from django.db import migrations

OFFICIAL_GROUP_NAME = "Official"


def create_official_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name=OFFICIAL_GROUP_NAME)


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("auth", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(create_official_group, migrations.RunPython.noop),
    ]
