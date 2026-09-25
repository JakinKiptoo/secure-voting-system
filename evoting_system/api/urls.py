"""
Empty DRF router (Sprint 1 scope: "DRF installed and wired up --
no endpoints yet"). Viewsets get registered here starting Sprint 2
(voter auth) and Sprint 3 (ballot casting), Sprint 4 (public tally).
"""

from rest_framework.routers import DefaultRouter

router = DefaultRouter()

# TODO(Sprint 2+): router.register("voters", VoterViewSet)
# TODO(Sprint 3+): router.register("ballots", BallotViewSet)
# TODO(Sprint 4+): router.register("tally", TallyViewSet)  -- FR-P-01

urlpatterns = router.urls
