from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _create_auditor_group(sender, **kwargs):
    """
    Idempotently creates the "Auditor" Django Group -- the FR-AUD role
    this app checks against, via common.roles.has_role()/role_required().

    Per Thread A, Part 2's explicit instruction, this is done via a
    post_migrate signal + get_or_create, NOT a data migration (contrast
    with Part 1's "Official" group, which officials/migrations/0001_
    create_official_group.py creates via migrations.RunPython -- see
    the handover for why Auditor deliberately does this differently).

    get_or_create makes repeat firings of this signal (every migrate
    run, including ones where nothing changed) safe: the group is
    created once and simply fetched on every subsequent run.

    Unlike officials/apps.py's post_migrate handler, this one grants no
    admin model permission -- the Auditor dashboard (AuditLog browser,
    chain-integrity check, DPA checklist) is entirely plain custom
    views, never Django admin's changelist, so there's no admin-only
    permission an Auditor account needs in order to reach them.
    """
    from django.contrib.auth.models import Group

    Group.objects.get_or_create(name="Auditor")


class AuditorsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "auditors"

    def ready(self):
        post_migrate.connect(_create_auditor_group, sender=self)
