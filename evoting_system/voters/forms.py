from django import forms

from .crypto_utils import sha256_hex
from .models import Voter


class VoterRegistrationForm(forms.Form):
    """FR-V-00: National ID + full name + phone number, National ID uniqueness."""

    national_id = forms.CharField(max_length=64, label="National ID")
    full_name = forms.CharField(max_length=255)
    phone_number = forms.CharField(max_length=20)

    def clean_national_id(self):
        national_id = self.cleaned_data["national_id"]
        national_id_hash = sha256_hex(national_id)
        if Voter.objects.filter(national_id_hash=national_id_hash).exists():
            # Deliberately generic: doesn't confirm *whose* ID this is,
            # just that registration under it already happened.
            raise forms.ValidationError("This National ID is already registered.")
        return national_id


class CredentialForm(forms.Form):
    """
    FR-V-01: National ID + phone number as credentials.

    The Authentication Flow sequence diagram (DIAGRAMS.md S4.5.3)
    abstracts this first step as "Submit National ID"; FR-V-01
    additionally requires the phone number. Both are collected in one
    step here and evaluated together against the Voter record -- see
    voters/views.py docstring for why that's treated as satisfying
    both without contradicting the diagram's step order.
    """

    national_id = forms.CharField(max_length=64, label="National ID")
    phone_number = forms.CharField(max_length=20)


class OTPForm(forms.Form):
    """FR-V-03: OTP submission to complete MFA."""

    otp = forms.CharField(max_length=6, min_length=6, label="One-Time PIN")
