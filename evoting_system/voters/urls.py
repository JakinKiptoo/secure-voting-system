from django.urls import path

from . import views

app_name = "voters"

urlpatterns = [
    path("register/", views.register_view, name="register"),
    path("login/", views.credentials_view, name="credentials"),
    path("verify-otp/", views.verify_otp_view, name="verify_otp"),
]
