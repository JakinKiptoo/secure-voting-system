"""
Local development settings.

Usage: set DJANGO_SETTINGS_MODULE=config.settings.local (see SETUP.md
and .env.example). DEBUG defaults on for local work but is still read
from the environment so it can be forced off if needed.
"""

from .base import *  # noqa: F401,F403
from decouple import config

DEBUG = config("DJANGO_DEBUG", default=True, cast=bool)

ALLOWED_HOSTS = ["localhost", "127.0.0.1"]

# Relaxed for local HTTP development only — production.py enforces
# HTTPS/TLS 1.3 per NFR-SE-01.
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
