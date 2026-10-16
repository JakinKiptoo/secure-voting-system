"""
Thread A, Part 3: the login VIEW half of the staff post-login
auto-redirect feature. See common/staff_login_redirect.py for the
role-checking redirect target this feeds into.

Why this exists at all, instead of just setting LOGIN_REDIRECT_URL:
Django's own admin login (django.contrib.admin.sites.AdminSite.login)
hardcodes its post-login destination to admin:index whenever the
request doesn't already carry an explicit ?next= -- it does this by
injecting "next": reverse("admin:index") straight into the template
context before delegating to the ordinary auth LoginView, which means
settings.LOGIN_REDIRECT_URL is never consulted on a plain visit to
/admin/login/ (only an explicit ?next= would override it). So setting
LOGIN_REDIRECT_URL alone cannot change where a staff member lands
after logging in at /admin/login/ the normal way.

StaffLoginView below is Django's OWN, unmodified LoginView, configured
with the exact same AdminAuthenticationForm and admin/login.html
template the real admin login uses -- so the page looks and behaves
identically, and no new login form, field, or credential type is
introduced. The only behavioural difference: it does NOT inject its
own default "next" value, so Django's ordinary redirect fallback
(LOGIN_REDIRECT_URL) is what decides where a successful login goes.

Mounted at the same /admin/login/ path, ahead of admin.site.urls in
config/urls.py, so this is what actually serves that path. admin.site
still registers its own "login" URL name under the "admin" namespace
as part of admin.site.urls -- left completely alone -- so
reverse("admin:login") (used by common/roles.py's role_required, and
by anything else in the project) keeps resolving to this exact path;
only the view that path dispatches to has changed.
"""

from django.contrib import admin
from django.contrib.admin.forms import AdminAuthenticationForm
from django.contrib.auth.views import LoginView


class StaffLoginView(LoginView):
    template_name = "admin/login.html"
    authentication_form = AdminAuthenticationForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        # admin/login.html extends admin/base_site.html, which needs
        # the usual AdminSite context (site_header, has_permission,
        # available_apps, etc.) to render correctly -- a plain
        # LoginView doesn't supply those, so pull in exactly what
        # admin.site.login() itself would have provided.
        context = super().get_context_data(**kwargs)
        context.update(admin.site.each_context(self.request))
        context["app_path"] = self.request.get_full_path()
        context.setdefault("title", "Log in")
        context.setdefault("subtitle", None)
        return context
