from django.urls import path

from . import views

app_name = "ballots"

urlpatterns = [
    path("cast/", views.cast_ballot_view, name="cast"),
]
