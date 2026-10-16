# No new persisted entity here. FR-OFF-01's staff-side Role concept
# ("Official" vs a plain Django superuser/staff account) is
# implemented with Django's own built-in auth.Group model instead of
# a new table/profile model here -- see officials/permissions.py for
# the reasoning. This file exists only so Django recognises
# `officials` as a normal app with its own migrations (the group-
# creation data migration lives in officials/migrations/).
