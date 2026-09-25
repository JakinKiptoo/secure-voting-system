# Deliberately no ModelAdmin registered for AuditLog in Sprint 1.
#
# FR-DB-01 requires AuditLog to be insert-only at the PostgreSQL role
# level (not yet configured -- see SETUP.md TODO and auditlog/models.py
# docstring). A default ModelAdmin would let a Django admin user
# edit/delete rows through the ORM, which is the exact behaviour
# FR-DB-01 exists to prevent. Once the DB-level GRANT/REVOKE lands,
# revisit whether a read-only ModelAdmin (list/view only, no
# add/change/delete permissions) is useful for operational visibility.
