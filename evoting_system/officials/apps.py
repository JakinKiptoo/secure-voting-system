from django.apps import AppConfig
from django.db.models.signals import post_migrate


def _grant_official_permissions(sender, **kwargs):
    """
    Grants the "Official" group the one Django permission it needs to
    use the dashboard's "Open voting"/"Close voting" quick-link
    buttons: elections.change_election. Those buttons POST directly
    to Django admin's existing Election changelist, which runs the
    existing open_elections/close_elections actions (elections/
    admin.py) -- no new open/close logic lives here. But admin's
    changelist_view() requires view-or-change permission on Election
    just to be reached at all, independent of which action is
    invoked, and "Official" is deliberately NOT superuser (FR-OFF-01
    distinguishes it from a plain superuser/staff account) -- so this
    one narrowly-scoped permission is what lets a non-superuser
    Official actually use the buttons.

    Done via post_migrate rather than inside the 0001 migration's
    RunPython: a migration executes before Django's one-time creation
    of each model's default Permission rows (which happens via this
    same post_migrate signal, fired only after every migration in the
    run has already applied), so looking up "change_election" from
    inside a migration is a race that can find nothing to attach.
    `sender=officials' own AppConfig` and officials being listed last
    in LOCAL_APPS means this fires after elections' permissions
    already exist.
    """
    from django.contrib.auth.models import Group, Permission

    try:
        group = Group.objects.get(name="Official")
    except Group.DoesNotExist:
        return  # officials' own migration hasn't run in this invocation

    try:
        change_election_perm = Permission.objects.get(
            codename="change_election", content_type__app_label="elections"
        )
    except Permission.DoesNotExist:
        return  # elections app wasn't migrated in this run

    group.permissions.add(change_election_perm)


class OfficialsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "officials"

    def ready(self):
        post_migrate.connect(_grant_official_permissions, sender=self)
