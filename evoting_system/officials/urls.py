from django.urls import path

from . import views

app_name = "officials"

urlpatterns = [
    # Thread D, Part B: the old single "dashboard/" page is now a
    # three-view sidebar shell. "dashboard/" itself is kept as a
    # redirect to overview/ so any old bookmark/link still lands
    # somewhere sensible, rather than 404ing.
    path("dashboard/", views.dashboard_redirect_view, name="dashboard"),
    path("overview/", views.overview_view, name="overview"),
    path("elections/", views.elections_view, name="elections"),
    path("candidates/", views.candidates_view, name="candidates"),
    # FR-OFF-05 (EXTENSIONS_ROADMAP.md): display-only results page,
    # reachable from the Elections list for a CLOSED election.
    path("elections/<uuid:election_id>/results/", views.results_view, name="results"),
]