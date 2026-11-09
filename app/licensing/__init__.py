"""Offline Ed25519 PC-locked licensing package for UIIC Surveyor Automation."""

from app.licensing.codec import (
    SignedLicense,
    VerifiedPayload,
    format_lic_file_content,
    generate_keypair,
    load_private_key,
    sign_license_token,
)
from app.licensing.fingerprint import (
    FingerprintError,
    FingerprintMatchResult,
    decode_request_code,
    encode_request_code,
    get_request_code,
    match_fingerprints,
)
from app.licensing.public_key import (
    PUBLIC_KEY_B64,
    PublicKeyNotConfiguredError,
    is_public_key_configured,
)
from app.licensing.verifier import (
    LicenseRequiredError,
    LicenseStatus,
    activate_from_file,
    activate_license,
    default_license_path,
    is_test_bypass_active,
    require_valid_license,
    verify_license_token,
    verify_stored_license,
)

__all__ = [
    "FingerprintError",
    "FingerprintMatchResult",
    "LicenseRequiredError",
    "LicenseStatus",
    "PUBLIC_KEY_B64",
    "PublicKeyNotConfiguredError",
    "SignedLicense",
    "VerifiedPayload",
    "activate_from_file",
    "activate_license",
    "decode_request_code",
    "default_license_path",
    "encode_request_code",
    "format_lic_file_content",
    "generate_keypair",
    "get_request_code",
    "is_public_key_configured",
    "is_test_bypass_active",
    "load_private_key",
    "match_fingerprints",
    "require_valid_license",
    "sign_license_token",
    "verify_license_token",
    "verify_stored_license",
]
