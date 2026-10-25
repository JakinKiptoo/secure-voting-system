"""
Tally and Verification Module -- views.

Two unauthenticated public views (FR-P-01/FR-P-02, CLAUDE.md invariant
#4: "the public tally/ZKP/audit endpoint takes no authentication --
don't add a login wall to it later") and one role-gated action
(FR-EL-03's publish step, item 2 -- the only authenticated view in
this whole module).
"""

from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render

from elections.models import Election

from .models import ElectionResult
from .permissions import publisher_required
from .services import get_verification_payload, publish_results


def public_index_view(request):
    """
    FR-P-01's entry point: a plain, unauthenticated list of every
    election and whether its results are available yet, so a Public
    Verifier has somewhere to start from without being told a UUID out
    of band. Only Election's own public fields (title, status) are
    shown -- exactly what FR-A-05 already treats as fine to expose,
    nothing about ballots or voters.
    """
    elections = Election.objects.order_by("-start_date")
    published_ids = set(
        ElectionResult.objects.filter(published=True).values_list("election_id", flat=True)
    )
    rows = [
        {"election": election, "has_results": election.election_id in published_ids}
        for election in elections
    ]
    return render(request, "tally/index.html", {"rows": rows})


def public_verify_view(request, election_id):
    """
    FR-P-01/FR-P-02: the public verification page for ONE election
    (item 1's per-election scoping, enforced here too -- this view
    only ever computes/reads a payload for the single `election_id` in
    the URL, never anything cross-election). No authentication, no
    login_required, no staff/role check -- this must stay reachable by
    anyone, per CLAUDE.md invariant #4.

    `?reverify=1` opts into the slower, live re-verification path
    (services.py::get_verification_payload(deep_verify=True)) that
    re-runs the real pairing check and re-digests this election's
    AuditLog slice against live data, rather than only showing the
    outcome recorded at publish time. Left off by default so the
    ordinary page load stays fast (NFR-PE-01) -- see that function's
    docstring for the reasoning.
    """
    election = get_object_or_404(Election, pk=election_id)
    deep_verify = request.GET.get("reverify") in ("1", "true", "True")
    payload = get_verification_payload(election, deep_verify=deep_verify)

    return render(
        request,
        "tally/verify.html",
        {"payload": payload, "deep_verify": deep_verify},
    )


@publisher_required
def publish_results_view(request, election_id):
    """
    FR-EL-03 (item 2): the explicit "publish results" action. Official
    or Auditor role (tally/permissions.py::publisher_required), not a
    new permission system. GET renders a small confirmation form
    (standalone to tally/ -- this is NOT part of the Officials or
    Auditor dashboards, which the Sprint 4 prompt explicitly says not
    to touch beyond the shared chain-walk refactor); POST actually
    publishes.
    """
    election = get_object_or_404(Election, pk=election_id)

    if request.method == "POST":
        try:
            publish_results(election)
        except ValidationError as exc:
            return render(
                request,
                "tally/publish.html",
                {"election": election, "error": "; ".join(exc.messages)},
            )
        return redirect("tally:verify", election_id=election.election_id)

    return render(request, "tally/publish.html", {"election": election, "error": None})
