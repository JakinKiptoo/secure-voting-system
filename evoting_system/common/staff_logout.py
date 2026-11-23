"""
FR-NAV-01: staff logout, POST only.

Django 4.2's LogoutView still answers GET (deprecated; removed in
Django 5.0) and a state-changing GET can be triggered by any page or
image tag. This subclass restricts it to POST (+ OPTIONS), so the only
way to log out is the CSRF-protected form in the shared navigation.
It is Django's own LogoutView otherwise: logout() flushes the browser
session (including any voting keys held in it) and redirects home.
No new credential or session mechanism.
"""

from django.contrib.auth.views import LogoutView
from django.urls import reverse_lazy


class StaffLogoutView(LogoutView):
    http_method_names = ["post", "options"]
    next_page = reverse_lazy("home")
