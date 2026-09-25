"""
Base Django settings for the Kenyan Electronic Voting System (Sprint 1).

Shared by local.py and production.py. All environment-specific values
(secrets, hosts, database credentials) are read from environment
variables via python-decouple — nothing environment-specific is
hardcoded here. See SETUP.md for the required variables.

Stack is fixed per REQUIREMENTS.md §3 / Proposal §1.7: Django 4.2,
Python 3.11, PostgreSQL 15, DRF, plain Django templates. Do not add a
frontend framework or substitute the database engine here.
"""

from pathlib import Path

from decouple import Csv, config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# ------------------------------------------------------------------
# Core
# ------------------------------------------------------------------
SECRET_KEY = config("DJANGO_SECRET_KEY")
DEBUG = config("DJANGO_DEBUG", default=False, cast=bool)
ALLOWED_HOSTS = config("DJANGO_ALLOWED_HOSTS", default="", cast=Csv())

# ------------------------------------------------------------------
# Applications
#
# App list mirrors the six-module decomposition from REQUIREMENTS.md §4
# / NFR-MA-01, so module boundaries stay visible in INSTALLED_APPS
# rather than being folded into one monolithic app:
#   - voters          -> Voter Authentication Module (model only, Sprint 1)
#   - voter_sessions   -> Session Management Module (model only, Sprint 1)
#   - elections        -> Election Administration Module (Election, Candidate)
#   - ballots          -> Ballot Casting Module (model only, Sprint 1)
#   - auditlog         -> Audit Log Module (model only, Sprint 1)
# The Tally and Verification Module has no app yet — it is out of scope
# until Sprint 4 (REQUIREMENTS.md §8, CLAUDE.md sprint roadmap).
# ------------------------------------------------------------------
DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]

THIRD_PARTY_APPS = [
    "rest_framework",
]

LOCAL_APPS = [
    "voters",
    "voter_sessions",
    "elections",
    "ballots",
    "auditlog",
    "api",
]

INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# ------------------------------------------------------------------
# Database — PostgreSQL 15, configured entirely via environment
# variables (REQUIREMENTS.md §3: chosen for ACID compliance + RBAC).
# No engine substitution — sqlite is not used anywhere, including
# tests, so behaviour matches production Postgres from day one.
# ------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": config("DB_NAME"),
        "USER": config("DB_USER"),
        "PASSWORD": config("DB_PASSWORD"),
        "HOST": config("DB_HOST", default="localhost"),
        "PORT": config("DB_PORT", default="5432"),
    }
}

# ------------------------------------------------------------------
# Password validation
# ------------------------------------------------------------------
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------
# Internationalization
# ------------------------------------------------------------------
LANGUAGE_CODE = "en-us"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True

# ------------------------------------------------------------------
# Static files
# ------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# ------------------------------------------------------------------
# Django REST Framework — wired up empty per Sprint 1 scope.
# No endpoints, no auth classes configured yet; that starts in later
# sprints alongside the actual auth/ballot/tally views.
# ------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAdminUser",
    ],
}

# ------------------------------------------------------------------
# Transport security note (NFR-SE-01): HTTPS/TLS 1.3 is enforced at
# the deployment/reverse-proxy layer and in production.py's
# SECURE_* settings. Not meaningful for local HTTP development.
# ------------------------------------------------------------------
