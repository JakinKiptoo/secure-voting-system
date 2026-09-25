"""
URL configuration for the Kenyan Electronic Voting System.

Sprint 1 scope: a placeholder home page, the Django admin (used for
FR-A-01/FR-A-02 election/candidate CRUD), and an empty DRF router
mounted at /api/. No auth, ballot-casting, or tally URLs yet.
"""

from django.contrib import admin
from django.urls import include, path

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
]
