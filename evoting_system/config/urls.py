"""
URL configuration for the Kenyan Electronic Voting System.

Sprint 1: placeholder home page, Django admin (FR-A-01/FR-A-02), empty
DRF router mounted at /api/.
Sprint 2: the Voter Authentication Module's views, mounted at /voters/
(FR-V-00 to FR-V-03, FR-S-01, FR-G-01).
Sprint 3: the Ballot Casting Module's view, mounted at /ballots/
(FR-V-04 to FR-V-08, FR-A-03's ballot-side check).
Thread A, Part 1: the Officials Dashboard, mounted at /officials/
(FR-OFF-01 to FR-OFF-04, the officials-side half of FR-OFF/AUD-01).
Thread A, Part 2: the Auditor Dashboard, mounted at /auditors/
(FR-AUD-01 to FR-AUD-03, the auditor-side half of FR-OFF/AUD-01).
Thread A, Part 3: staff post-login auto-redirect. /admin/login/ is
overridden (BEFORE admin.site.urls below, so it's what actually
serves that path -- see common/admin_login.py) to route a successful
staff login through /post-login/ instead of admin's own hardcoded
admin:index default; /post-login/ (common/staff_login_redirect.py)
then sends the user straight to their dashboard by role. Nothing
about the anonymous Voter/OTP flow changes.
Thread D, Part A: the site root ("") now renders a pure navigational
landing page (config/views.py::home, templates/home.html) with no
authentication of its own -- just links to voters:credentials and
admin:login, both otherwise unchanged. No tally/public verification
URLs yet (Sprint 4).
"""

from django.contrib import admin
from django.urls import include, path

from common.admin_login import StaffLoginView
from common.staff_login_redirect import post_login_choose_view, post_login_redirect_view

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("admin/login/", StaffLoginView.as_view(), name="admin_login_override"),
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("voters/", include("voters.urls")),
    path("ballots/", include("ballots.urls")),
    path("officials/", include("officials.urls")),
    path("auditors/", include("auditors.urls")),
    path("post-login/", post_login_redirect_view, name="post_login_redirect"),
    path("post-login/choose/", post_login_choose_view, name="post_login_choose"),
]
