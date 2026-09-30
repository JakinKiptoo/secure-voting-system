"""
Hashing helpers shared across the Voter Authentication Module.

Uses the `cryptography` library (v41.x, REQUIREMENTS.md S3) rather
than `hashlib`, per the fixed-stack delimitation in Proposal S1.7 --
no substituting the specified crypto library even though hashlib's
sha256 would do the same job.

Used for both `national_id_hash` (FR-V-00/FR-V-01) and `otp_hash`
(FR-V-03). Both are one-way hashes: there is no "unhash" here by
design -- lookups always re-hash the submitted plaintext and compare
digests, never decrypt a stored value.
"""

from cryptography.hazmat.primitives import hashes


def sha256_hex(value: str) -> str:
    """Return the SHA-256 hex digest of `value` (UTF-8 encoded)."""
    digest = hashes.Hash(hashes.SHA256())
    digest.update(value.encode("utf-8"))
    return digest.finalize().hex()
