"""
Voter Authentication Module views.

Implements the Authentication Flow sequence diagram (DIAGRAMS.md
S4.5.3) as three server-rendered steps, matching the "Web Client
(Presentation Tier)" <-> "Authentication Module (Django Backend)"
split in that diagram and the System Architecture diagram (S4.5.6):
plain Django views + templates POST directly to this module, no
DRF/API layer involved (see Sprint 2 handover for why the DRF router
stays empty for this flow).

Flagged interpretation (per CLAUDE.md "flag it rather than silently
improving it"): the sequence diagram's first step is "Submit National
ID", but FR-V-01 requires National ID *and* phone number as
credentials. This isn't the kind of FR-vs-diagram *ordering* conflict
DIAGRAMS.md says to resolve in the diagram's favour (that guidance was
specifically about the ballot-casting step order) -- it reads as the
diagram abstracting "submit credentials" for brevity. `credentials_view`
below therefore collects both fields in one step and treats that as
satisfying the diagram's "Submit National ID" box. Also not pictured in
the diagram at all: what happens when no Voter record matches the
submitted credentials. The diagram only branches on has_voted, implicit
in a match already having been found. `credentials_view` adds a
"no such voter" rejection branch ahead of that, since the DB query has
to run before has_voted can even be checked.

DEBUG-only demo convenience: `SMSGatewayClient.send_otp()` (FR-G-01)
still only ever logs the OTP -- its behavior, return value, and
logging call are unchanged. Separately, when `settings.DEBUG` is True,
`credentials_view` stashes the plaintext OTP it already generated into
`request.session` purely so `verify_otp_view` can display it on-screen,
clearly labeled as a mock value, so the flow is demoable without a
working log handler. The stash only happens inside an `if
settings.DEBUG:` block and the template only renders the value if the
context key is present, so with `DEBUG=False` neither the session key
nor the on-page display exists at all -- there is no separate flag to
misconfigure.
"""

import secrets
from datetime import datetime, timedelta

from django.conf import settings
from django.shortcuts import redirect, render
from django.utils import timezone

from voter_sessions.services import VOTING_TOKEN_SESSION_KEY, issue_session

from . import sms_gateway
from .crypto_utils import sha256_hex
from .forms import CredentialForm, OTPForm, VoterRegistrationForm
from .models import Voter

OTP_LENGTH = 6
OTP_VALIDITY_MINUTES = 5

PENDING_VOTER_SESSION_KEY = "pending_auth_voter_id"
PENDING_EXPIRY_SESSION_KEY = "pending_auth_expiry"
DEBUG_MOCK_OTP_SESSION_KEY = "debug_mock_otp"


def _generate_otp() -> str:
    """Cryptographically secure numeric OTP, zero-padded to OTP_LENGTH digits."""
    return "".join(secrets.choice("0123456789") for _ in range(OTP_LENGTH))


def register_view(request):
    """FR-V-00: register a Voter with National ID, full name, phone number."""
    if request.method == "POST":
        form = VoterRegistrationForm(request.POST)
        if form.is_valid():
            Voter.objects.create(
                national_id_hash=sha256_hex(form.cleaned_data["national_id"]),
                full_name=form.cleaned_data["full_name"],
                phone_number=form.cleaned_data["phone_number"],
            )
            return render(request, "voters/register_success.html")
    else:
        form = VoterRegistrationForm()

    return render(request, "voters/register.html", {"form": form})


def credentials_view(request):
    """
    FR-V-01 (credential evaluation) + FR-V-02 (has_voted short-circuit)
    + the first half of FR-G-01 (requesting OTP delivery).

    Sequence diagram steps covered: "Submit National ID" / "Forward
    National ID" / "Query has_voted flag" / the has_voted alt-branch /
    "Request OTP delivery" / "Deliver OTP out-of-band".
    """
    if request.method == "POST":
        form = CredentialForm(request.POST)
        if form.is_valid():
            national_id_hash = sha256_hex(form.cleaned_data["national_id"])
            phone_number = form.cleaned_data["phone_number"]

            try:
                voter = Voter.objects.get(
                    national_id_hash=national_id_hash,
                    phone_number=phone_number,
                )
            except Voter.DoesNotExist:
                return render(
                    request,
                    "voters/auth_rejected.html",
                    {"reason": "Invalid credentials."},
                )

            # has_voted short-circuit (FR-V-02) -- rejected here, before
            # any OTP is requested, matching the diagram's alt-branch.
            if voter.has_voted:
                return render(
                    request,
                    "voters/auth_rejected.html",
                    {"reason": "This voter has already cast a ballot."},
                )

            otp = _generate_otp()
            voter.otp_hash = sha256_hex(otp)
            voter.save(update_fields=["otp_hash"])

            sms_gateway.send_otp(voter.phone_number, otp)

            request.session[PENDING_VOTER_SESSION_KEY] = str(voter.voter_id)
            request.session[PENDING_EXPIRY_SESSION_KEY] = (
                timezone.now() + timedelta(minutes=OTP_VALIDITY_MINUTES)
            ).isoformat()

            # Demo convenience only -- see module docstring. Does not
            # touch SMSGatewayClient.send_otp() above in any way.
            if settings.DEBUG:
                request.session[DEBUG_MOCK_OTP_SESSION_KEY] = otp

            return redirect("voters:verify_otp")
    else:
        form = CredentialForm()

    return render(request, "voters/credentials.html", {"form": form})


def verify_otp_view(request):
    """
    FR-V-03 (OTP match against hashed secret) + FR-S-01 (token issuance
    on successful MFA).

    Sequence diagram steps covered: "Submit OTP" / "Forward OTP" /
    "Match OTP against hashed secret" / "Issue session-bound UUID
    token" / "Token issued" / "Return UUID token" / "Session
    established".
    """
    pending_voter_id = request.session.get(PENDING_VOTER_SESSION_KEY)
    pending_expiry = request.session.get(PENDING_EXPIRY_SESSION_KEY)

    if not pending_voter_id or not pending_expiry:
        return redirect("voters:credentials")

    if timezone.now() > datetime.fromisoformat(pending_expiry):
        del request.session[PENDING_VOTER_SESSION_KEY]
        del request.session[PENDING_EXPIRY_SESSION_KEY]
        request.session.pop(DEBUG_MOCK_OTP_SESSION_KEY, None)
        return render(
            request,
            "voters/auth_rejected.html",
            {"reason": "OTP expired. Please start again."},
        )

    if request.method == "POST":
        form = OTPForm(request.POST)
        if form.is_valid():
            try:
                voter = Voter.objects.get(voter_id=pending_voter_id)
            except Voter.DoesNotExist:
                return redirect("voters:credentials")

            submitted_hash = sha256_hex(form.cleaned_data["otp"])
            if submitted_hash != voter.otp_hash:
                form.add_error("otp", "Incorrect OTP.")
            else:
                # Single-use: clear the OTP hash so it can't be replayed.
                voter.otp_hash = ""
                voter.save(update_fields=["otp_hash"])

                session = issue_session(voter)

                del request.session[PENDING_VOTER_SESSION_KEY]
                del request.session[PENDING_EXPIRY_SESSION_KEY]
                request.session.pop(DEBUG_MOCK_OTP_SESSION_KEY, None)
                request.session[VOTING_TOKEN_SESSION_KEY] = str(session.uuid_token)

                return render(
                    request,
                    "voters/auth_success.html",
                    {"expiry_time": session.expiry_time},
                )
    else:
        form = OTPForm()

    context = {"form": form}
    # Demo convenience only (see module docstring): the key -- and
    # therefore the on-page display -- exists only when DEBUG is True.
    if settings.DEBUG:
        context["debug_otp"] = request.session.get(DEBUG_MOCK_OTP_SESSION_KEY)

    return render(request, "voters/verify_otp.html", context)
