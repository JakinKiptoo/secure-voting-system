from django.urls import path

from . import views

app_name = "auditors"

urlpatterns = [
    path("", views.dashboard_view, name="dashboard"),
    path("audit-log/", views.audit_log_list_view, name="audit_log_list"),
    path("audit-log/verify/", views.verify_chain_view, name="verify_chain"),
    path("compliance/", views.dpa_checklist_view, name="dpa_checklist"),
]
