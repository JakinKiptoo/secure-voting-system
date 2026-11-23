"""
Local development settings.

Usage: set DJANGO_SETTINGS_MODULE=config.settings.local (see SETUP.md
and .env.example). DEBUG defaults on for local work but is still read
from the environment so it can be forced off if needed.
"""

from .base import *  # noqa: F401,F403
from decouple import Csv, config

DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Relaxed for local HTTP development only — production.py enforces
# HTTPS/TLS 1.3 per NFR-SE-01.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False

# Local TLS reverse proxy (e.g. Caddy at https://localhost:8443) for the
# Chapter 5.4 security run. Both are inert unless the variable is set:
# DJANGO_CSRF_TRUSTED_ORIGINS=https://localhost:8443 (comma-separated).
# The proxy header is trusted only when origins are configured, so plain
# local HTTP behaves exactly as before.
CSRF_TRUSTED_ORIGINS = config("DJANGO_CSRF_TRUSTED_ORIGINS", default="", cast=Csv())
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https") if CSRF_TRUSTED_ORIGINS else None
