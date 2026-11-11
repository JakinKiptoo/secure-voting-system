"""
Demo settings (DEMO TOOLING ONLY) -- identical to config.settings.local
except that INFO-level log lines from the stub SMS gateway are printed to
the runserver console, so the presenter can show where the stub "delivers"
the OTP (FR-G-01).

Without this module the Django project has no LOGGING configuration for the
"voters.sms_gateway" logger, so its INFO line is silently dropped (verified:
see DEMO_RUNBOOK.md S3). Nothing else changes: same DEBUG, same security
settings, same everything. Use:

    DJANGO_SETTINGS_MODULE=config.settings.demo python manage.py runserver
"""

from .local import *  # noqa: F401,F403

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"demo": {"format": "[%(levelname)s] %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "demo"}},
    "loggers": {"voters.sms_gateway": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
