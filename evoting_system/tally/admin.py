from django.contrib import admin

from .models import ElectionResult


@admin.register(ElectionResult)
class ElectionResultAdmin(admin.ModelAdmin):
    """
    Read-only visibility into published results for staff browsing the
    admin -- NOT the publish action itself (that's
    tally/views.py::publish_results_view, role-gated by
    tally/permissions.py::publisher_required, reachable at
    /tally/<election_id>/publish/). Every field is read-only and
    nothing is addable/deletable here: publish_results() is the only
    code path allowed to create a row (it enforces the CLOSED-only and
    no-republish rules -- bypassing it via a raw admin "Add" form would
    skip both).
    """

    list_display = ("election", "published", "published_at", "total_ballots")
    list_filter = ("published",)
    readonly_fields = (
        "result_id",
        "election",
        "published",
        "published_at",
        "total_ballots",
        "candidate_counts",
        "commitment_total_g1",
        "commitment_total_g2",
        "candidate_commitments_g1",
        "audit_entries_digest",
        "chain_intact_at_publish",
        "chain_entries_checked_at_publish",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False
