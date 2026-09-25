# Deliberately no ModelAdmin registered for Ballot.
#
# FR-A-05 requires the Administrator's view to expose no per-ballot
# detail. FR-P-03 separately requires the *public* tally endpoint to
# reveal nothing that could reconstruct an individual's vote. Neither
# requirement is served by an admin list/detail page over raw Ballot
# rows, so none is provided. Do not add one in a later sprint without
# re-checking both requirements.
