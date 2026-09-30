"""
External SMS Gateway -- stub client (FR-G-01, DIAGRAMS.md class
diagram `SMSGatewayClient <<external, stateless>>`).

Per the Sprint 2 prompt: "a stub that logs or returns the OTP is
fine; don't wire a real SMS provider." This client never sends a
real SMS. It logs the delivery attempt (server-side only, via the
standard logging module -- never returned in an HTTP response, so a
stub OTP still isn't visible to anything watching network traffic,
preserving the point of MFA even in proof-of-concept form) and
reports a synthetic delivery confirmation, matching FR-G-01's
"confirms delivery" requirement.

Swap this module's internals for a real provider (e.g. Africa's
Talking, Twilio) when the project moves past proof-of-concept --
nothing outside this file should need to change, since callers only
see `sms_gateway.send_otp(phone_number, otp)` and a boolean result.
"""

import logging

logger = logging.getLogger("voters.sms_gateway")


class SMSGatewayClient:
    """Stateless stub matching the class diagram's SMSGatewayClient."""

    def send_otp(self, phone_number: str, otp: str) -> bool:
        """
        "Deliver" an OTP out-of-band and confirm delivery (FR-G-01).

        Logs at INFO level instead of sending a real SMS. Always
        returns True (delivery confirmed) -- there is no real
        gateway to fail against in this proof-of-concept.
        """
        logger.info("Stub SMS gateway: delivering OTP %s to %s", otp, phone_number)
        return True


def send_otp(phone_number: str, otp: str) -> bool:
    """Module-level convenience wrapper around SMSGatewayClient."""
    return SMSGatewayClient().send_otp(phone_number, otp)
