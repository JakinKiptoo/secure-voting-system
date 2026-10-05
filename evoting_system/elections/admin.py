from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from .models import Candidate, Election


class CandidateInline(admin.TabularInline):
    """
    FR-A-04: once the parent Election is no longer DRAFT, disallow
    adding/changing/deleting candidates from this inline. Candidate.
    clean()/save() enforce the same rule at the model layer (so it
    holds even outside the admin) -- this just gives a clean read-only
    UI instead of a raised ValidationError on submit.
    """

    model = Candidate
    extra = 1
    fields = ("name", "party", "biography")

    def has_add_permission(self, request, obj=None):
        if obj is not None and obj.status != Election.Status.DRAFT:
            return False
        return super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        if obj is not None and obj.status != Election.Status.DRAFT:
            return False
        return super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.status != Election.Status.DRAFT:
            return False
        return super().has_delete_permission(request, obj)


@admin.action(description="Open voting")
def open_elections(modeladmin, request, queryset):
    for election in queryset:
        try:
            election.open_voting()
        except ValidationError as exc:
            modeladmin.message_user(request, f"{election}: {exc}", level=messages.ERROR)
        else:
            modeladmin.message_user(request, f"Opened '{election}' for voting.")


@admin.action(description="Close voting")
def close_elections(modeladmin, request, queryset):
    for election in queryset:
        try:
            election.close_voting()
        except ValidationError as exc:
            modeladmin.message_user(request, f"{election}: {exc}", level=messages.ERROR)
        else:
            modeladmin.message_user(request, f"Closed '{election}'.")


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    """
    Election Administration Module CRUD -- FR-A-01 (create an election),
    FR-A-02 (register candidates, via the inline below), FR-A-03 (open/
    close a voting period, via the "Open voting"/"Close voting" admin
    actions below -- the other half of FR-A-03, rejecting ballots
    submitted outside an open period, lives in
    ballots/services.py:cast_ballot), and FR-A-04 (candidate locking
    once OPEN, via CandidateInline's permission overrides +
    Candidate.clean()).

    Bug fix: `status` is now in `readonly_fields`. It was previously
    just left out of any explicit read-only/editable configuration,
    which meant Django's default ModelForm behaviour applied: the
    change form rendered it as a normal editable dropdown that, if
    submitted, would write whatever value was chosen straight to the
    database via the model's plain save() -- completely bypassing
    open_voting()/close_voting() and the DRAFT -> OPEN -> CLOSED
    transition rule they enforce. A comment here previously claimed
    this was "deliberately left off... direct editing", which was
    aspirational, not actual -- the field was never made read-only in
    code. `readonly_fields` is what actually enforces it: the field is
    still visible on the change form (showing the human-readable
    choice label, since Django's admin applies `flatchoices` to
    read-only fields with `choices` -- not the raw stored value), but
    no longer submittable. "Open voting"/"Close voting" are the only
    way to transition it now, in practice as well as in the docstring.
    """

    list_display = ("title", "start_date", "end_date", "status")
    list_filter = ("status",)
    search_fields = ("title",)
    readonly_fields = ("status",)
    inlines = [CandidateInline]
    actions = [open_elections, close_elections]


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    """
    Standalone Candidate admin (FR-A-02), in addition to the inline
    above. FR-A-04 is enforced in Candidate.clean()/save() (model
    layer), so attempting to add/edit a candidate for a non-DRAFT
    election here raises a validation error on submit, same as the
    inline -- just without the extra has_*_permission UI polish.
    """

    list_display = ("name", "party", "election")
    list_filter = ("election",)
    search_fields = ("name", "party")
