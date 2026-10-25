from django.urls import path

from . import views

app_name = "tally"

urlpatterns = [
    path("", views.public_index_view, name="index"),
    path("<uuid:election_id>/", views.public_verify_view, name="verify"),
    path("<uuid:election_id>/publish/", views.publish_results_view, name="publish"),
]
