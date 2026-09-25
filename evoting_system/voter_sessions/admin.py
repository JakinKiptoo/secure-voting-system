# Deliberately no ModelAdmin registered for Session, for the same
# reason as voters/admin.py: a Session row is voter-identifying
# (FK to Voter) and per-voter detail must not be exposed in the
# Administrator's admin UI (FR-A-05).
