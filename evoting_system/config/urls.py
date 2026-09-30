"""
URL configuration for the Kenyan Electronic Voting System.

Sprint 1: placeholder home page, Django admin (FR-A-01/FR-A-02), empty
DRF router mounted at /api/.
Sprint 2: the Voter Authentication Module's views, mounted at /voters/
(FR-V-00 to FR-V-03, FR-S-01, FR-G-01). No ballot-casting or tally
URLs yet.
"""

from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("voters/", include("voters.urls")),
]
