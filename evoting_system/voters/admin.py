# Deliberately no ModelAdmin registered for Voter.
#
# FR-A-05 (REQUIREMENTS.md) requires the Administrator's operational
# view to stay aggregate-only, with no per-voter detail exposed --
# including in an internal admin UI (FRONTEND_STYLE.md "What NOT to
# borrow"). Registering Voter in Django admin would let an
# Administrator browse individual voters, which is out of scope for
# this role. If a future sprint needs *any* admin-visible voter data,
# it must be an aggregate/count view, not a Voter list/detail page.
