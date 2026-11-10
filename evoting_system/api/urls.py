"""
DRF router. Sprint 1 wired it up empty; Sprint 2 (voter auth) and
Sprint 3 (ballot casting) still have no DRF viewsets of their own --
those modules were built as plain Django views instead (voters/views.py,
ballots/views.py) -- so "tally" below is this router's first real
registration.

Sprint 4: "tally" is FR-P-01's machine-readable endpoint
(GET /api/tally/<election_id>/) -- see tally/api_views.py.
tally/views.py::public_verify_view is the human-readable counterpart
(FR-P-02) at /tally/<election_id>/, mounted directly in config/urls.py
rather than through this DRF router, since it's a plain Django
template view, not an API viewset.
"""

from rest_framework.routers import DefaultRouter

from tally.api_views import TallyViewSet

router = DefaultRouter()
router.register("tally", TallyViewSet, basename="tally")

urlpatterns = router.urls
