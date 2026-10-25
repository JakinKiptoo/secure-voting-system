"""
FR-P-01's machine-readable endpoint: the DRF side of the Tally and
Verification Module, registered in api/urls.py at /api/tally/
(replacing that file's Sprint-1 TODO placeholder for this exact
module). tally/views.py::public_verify_view is the human-readable
counterpart (FR-P-02) at /tally/<election_id>/ -- both call the same
tally/services.py::get_verification_payload(), so they can't disagree
about what "published"/"not yet available" means.

No authentication/permission class restricts this -- `permission_classes
= [AllowAny]` is explicit (not just "nothing configured") so this
endpoint can never silently inherit a project-wide default permission
class added later. CLAUDE.md invariant #4 applies here exactly as it
does to the HTML page.
"""

from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from elections.models import Election

from .services import get_verification_payload


class TallyViewSet(ViewSet):
    """
    GET /api/tally/<election_id>/        -- published-at-publish-time
                                             outcome (fast path).
    GET /api/tally/<election_id>/?reverify=1
                                          -- additionally re-runs the
                                             live pairing/chain checks
                                             (slower -- opt-in, see
                                             services.py).

    `election_id` doubles as the DRF `pk` lookup -- there's no
    separate "tally" primary key; the tally IS the election's, scoped
    1:1 the same way item 1 requires everywhere else in this sprint.
    """

    permission_classes = [AllowAny]
    lookup_value_regex = "[0-9a-f-]{36}"  # UUID

    def retrieve(self, request, pk=None):
        election = Election.objects.filter(pk=pk).first()
        if election is None:
            return Response({"detail": "No such election."}, status=404)

        deep_verify = request.query_params.get("reverify") in ("1", "true", "True")
        payload = get_verification_payload(election, deep_verify=deep_verify)
        return Response(payload.to_json_dict())
