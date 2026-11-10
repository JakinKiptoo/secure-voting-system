"""
Sprint 5 gap fill: config/views.py::home (Thread D, Part A) had no test
coverage at all before this file -- it's the site's root ("") landing
page and the very first thing a real voter or official sees, so a
broken link here would block entry to both the FR-V (voter) and
FR-OFF/FR-AUD (staff) flows before they even start. This page itself
carries no FR/NFR ID of its own (it is "pure navigation", per its own
docstring), but the two flows it links into do, so this test proves
the links are wired to the real named routes, not hardcoded/broken
paths.
"""

import pytest
from django.urls import reverse


@pytest.mark.django_db
def test_home_page_renders_and_links_to_both_entry_points(client):
    response = client.get(reverse("home"))
    body = response.content.decode()

    assert response.status_code == 200
    # Voter entry points (FR-V-00 registration, FR-V-01 login).
    assert reverse("voters:register") in body
    assert reverse("voters:credentials") in body
    # Staff entry point (Thread A, Part 3's role-redirecting login).
    assert reverse("admin:login") in body
