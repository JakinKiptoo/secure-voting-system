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
from decouple import config

# Optional: run the demo web server as the restricted runtime role
# (FR-DB-01), the way config.settings.production does. Set DEMO_DB_AS_APP=1
# for runserver only; seed_demo and reset_demo must run WITHOUT it, as the
# owner (reset_demo deletes ballots and audit rows, which the restricted
# role may not do).
if config("DEMO_DB_AS_APP", default=False, cast=bool):
    DATABASES["default"]["USER"] = config("DB_APP_USER")  # noqa: F405
    DATABASES["default"]["PASSWORD"] = config("DB_APP_PASSWORD")  # noqa: F405

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {"demo": {"format": "[%(levelname)s] %(name)s: %(message)s"}},
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "demo"}},
    "loggers": {"voters.sms_gateway": {"handlers": ["console"], "level": "INFO", "propagate": False}},
}
