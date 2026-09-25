from django.contrib import admin

from .models import Candidate, Election


class CandidateInline(admin.TabularInline):
    model = Candidate
    extra = 1
    fields = ("name", "party", "biography")


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    """
    Election Administration Module CRUD -- FR-A-01 (create an election:
    title, opening/closing times) and FR-A-02 (register candidates,
    via the inline below), exposed through Django admin per Sprint 1
    scope.

    TODO (FR-A-03, Sprint 2+): open/close a voting period and reject
    ballots submitted outside it. Not implemented -- `status` is a
    free-text field with no enforced state machine yet.

    TODO (FR-A-04, Sprint 2+): block candidate additions/modifications
    once voting has opened, enforced at the schema level. Not
    implemented -- the CandidateInline below allows edits regardless
    of `status`. Do not implement this locking logic in Sprint 1.
    """

    list_display = ("title", "start_date", "end_date", "status")
    list_filter = ("status",)
    search_fields = ("title",)
    inlines = [CandidateInline]

    # TODO(FR-A-03): override save_model / add a form-level check once
    # the open/close lifecycle is implemented, to reject transitions
    # that would violate the voting-period rule.

    # TODO(FR-A-04): override get_readonly_fields / has_change_permission
    # on CandidateInline once candidate-locking is implemented, keyed
    # off Election.status.


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    """Standalone Candidate admin (FR-A-02), in addition to the inline above."""

    list_display = ("name", "party", "election")
    list_filter = ("election",)
    search_fields = ("name", "party")
