"""
Production settings.

Usage: set DJANGO_SETTINGS_MODULE=config.settings.production. Every
value that must differ between environments comes from the process
environment (see SETUP.md) — nothing production-specific is hardcoded
here beyond the security hardening flags required by NFR-SE-01.
"""

from .base import *  # noqa: F401,F403
from decouple import config

DEBUG = False

# ALLOWED_HOSTS must be set explicitly via env var in production —
# base.py already reads DJANGO_ALLOWED_HOSTS; re-enforced here so a
# missing/blank value fails loudly rather than defaulting to "*".
if not ALLOWED_HOSTS:  # noqa: F405
    raise ValueError("DJANGO_ALLOWED_HOSTS must be set in production")

# ------------------------------------------------------------------
# HTTPS / TLS 1.3 enforcement (NFR-SE-01). Actual TLS termination is
# handled by the reverse proxy/load balancer per the deployment
# environment — these flags make Django itself refuse to serve or
# accept anything over plain HTTP once that's in place.
# ------------------------------------------------------------------
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_HSTS_SECONDS = 31536000
SECURE_HSTS_INCLUDE_SUBDOMAINS = True
SECURE_HSTS_PRELOAD = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

# TODO(Sprint 5): revisit alongside the Burp Suite / SQLMap security
# testing pass and the DPA-2019 checklist (REQUIREMENTS.md §8).
