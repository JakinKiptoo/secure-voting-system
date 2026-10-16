from django.shortcuts import render


def home(request):
    """
    Thread D, Part A: the site's navigational landing page (FR-less --
    this page is pure navigation, not a requirement-bearing flow).

    Deliberately NOT a form view: no fields, no credential handling,
    no new model. It only links to the two authentication entry
    points that already exist and are otherwise unchanged --
    voters:credentials (the real start of the Voter OTP flow) and
    admin:login (the real start of the staff Official/Auditor login,
    which already auto-redirects by role after authenticating --
    Thread A, Part 3). Keeping this a single render() call, same as
    the Sprint 1 placeholder it replaces, is what keeps it a plain
    TemplateView-equivalent rather than growing into anything that
    could blur the two separate login paths NFR-SE-01 depends on
    staying apart.
    """
    return render(request, "home.html")
