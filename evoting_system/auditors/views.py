"""
Auditor Dashboard views: FR-AUD-01 (AuditLog browser), FR-AUD-02 (chain
integrity check), FR-AUD-03 (DPA-2019 checklist status). All gated by
@auditor_required (the auditor-side half of FR-OFF/AUD-01).

Guardrail #1/#2: none of these views ever dereference AuditLog.ballot
(the OneToOneField to Ballot) or otherwise query Ballot/Session/Voter
per-row. The AuditLog browser renders exactly AuditLog's own fields
(log_id, timestamp, action_type, ballot_hash, previous_hash) -- never
which candidate/election/voter a given hash belongs to.
"""

from django.core.paginator import Paginator
from django.shortcuts import render

from auditlog.models import AuditLog

from .permissions import auditor_required
from .services import verify_chain_integrity

PAGE_SIZE = 25


@auditor_required
def dashboard_view(request):
    """Auditor landing page: quick links to the three FR-AUD tools."""
    return render(request, "auditors/dashboard.html")


@auditor_required
def audit_log_list_view(request):
    """
    FR-AUD-01: paginated, filterable AuditLog browser.

    Pattern-adapted from the described Kva-system dashboard list view
    (Paginator + GET-param filtering) -- applied here to this project's
    own cryptographic auditlog.AuditLog model, which is an unrelated
    model that merely shares the "audit log" name with Kva-system's
    generic activity log.

    Filters (all optional, combined with AND):
      - action_type: exact match against AuditLog.action_type
      - date_from / date_to: inclusive range against timestamp's date

    Ordered newest-first (-log_id) for browsing, since that's the
    order an auditor is most likely to want to scan recent activity --
    this is distinct from FR-AUD-02's chain walk, which always goes
    oldest-first (log_id ascending) regardless of how this page is sorted.

    Only AuditLog's own columns are ever selected or rendered here --
    no join to Ballot, so there is nothing to leak about which
    candidate, election, or voter any given row's hash corresponds to.
    """
    entries = AuditLog.objects.order_by("-log_id")

    action_type = request.GET.get("action_type", "").strip()
    if action_type:
        entries = entries.filter(action_type=action_type)

    date_from = request.GET.get("date_from", "").strip()
    if date_from:
        entries = entries.filter(timestamp__date__gte=date_from)

    date_to = request.GET.get("date_to", "").strip()
    if date_to:
        entries = entries.filter(timestamp__date__lte=date_to)

    paginator = Paginator(entries, PAGE_SIZE)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    # action_type is a free-text CharField on AuditLog (no model-level
    # choices exist for it), so the filter is a plain text input rather
    # than a dropdown of guessed values -- it matches exactly whatever
    # action_type strings the Ballot Casting Module actually writes.
    return render(
        request,
        "auditors/audit_log_list.html",
        {
            "page_obj": page_obj,
            "selected_action_type": action_type,
            "date_from": date_from,
            "date_to": date_to,
        },
    )


@auditor_required
def verify_chain_view(request):
    """
    FR-AUD-02: runs the pure hash-chain walk (auditors/services.py) and
    renders its result -- "chain intact" or the exact break position.
    """
    result = verify_chain_integrity()
    return render(request, "auditors/verify_chain.html", {"result": result})


@auditor_required
def dpa_checklist_view(request):
    """
    FR-AUD-03: DPA-2019 compliance checklist status.

    Sprint 5 (per CLAUDE.md's roadmap) has not yet produced any actual
    checklist content in this repository (confirmed by grepping
    SETUP.md and the handover docs for one -- nothing exists), so this
    renders a clear "Sprint 5 not yet complete" placeholder rather than
    fabricating checklist items. When Sprint 5 does add real checklist
    data/a real source for it, this view should be updated to read and
    render it instead of this placeholder branch.
    """
    return render(
        request,
        "auditors/dpa_checklist.html",
        {"checklist_available": False},
    )
