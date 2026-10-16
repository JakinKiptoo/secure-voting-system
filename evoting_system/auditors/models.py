# Auditors app defines no persisted entity of its own.
#
# The "Auditor" Role (FR-AUD-01's auditor-side half of FR-OFF/AUD-01) is a
# django.contrib.auth Group, created idempotently via a post_migrate
# signal in auditors/apps.py -- not a new model/table here. This mirrors
# officials/models.py's pattern (that app also defines no model), and
# keeps this dashboard a purely read-only tool over auditlog.AuditLog
# (and, only for access control, django.contrib.auth) -- it never adds a
# table of its own, and never touches voters/voter_sessions/ballots'
# tables except indirectly in tests (to cast a real ballot to audit).
