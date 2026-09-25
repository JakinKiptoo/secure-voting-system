from django.shortcuts import render


def home(request):
    """
    Placeholder home page (Sprint 1 scope: minimal template shell
    only -- no voter-facing screens yet). Sprint 2+ replaces this
    with the actual authentication entry point.
    """
    return render(request, "home.html")
