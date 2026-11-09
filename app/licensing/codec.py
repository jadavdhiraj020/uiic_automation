"""
Compact Ed25519 binary license codec (signing & verification).

Binary payload layout (20 bytes):
  - magic       (2B): b"U1"
  - fp_bytes   (10B): packed machine fingerprint from Request Code
  - license_id  (4B): random unsigned 32-bit license identifier
  - issued_day  (2B): UTC days since 2026-01-01
  - flags       (2B): 0x0000 (permanent-only)

Signed binary token = 20-byte payload + 64-byte Ed25519 signature = 84 bytes.
Encoded string = "UIIC1-" + urlsafe_b64(84 bytes) = 118 ASCII characters exact.
"""

from __future__ import annotations

import base64
import json
import re
import secrets
import struct
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.licensing.fingerprint import DecodedFingerprint, decode_fingerprint_bytes, decode_request_code
from app.licensing.public_key import load_ed25519_public_key

TOKEN_PREFIX = "UIIC1-"
PAYLOAD_MAGIC = b"U1"
PAYLOAD_STRUCT = struct.Struct("!2s10sIHH")  # 20 bytes
SIGNATURE_LEN = 64
TOTAL_TOKEN_BYTES = PAYLOAD_STRUCT.size + SIGNATURE_LEN  # 84 bytes -> 112 base64url chars
ENCODED_BODY_LEN = 112
FLAGS_PERMANENT = 0
EPOCH_DATE = date(2026, 1, 1)
LIC_FILE_FORMAT = "uiic-license-v1"

_TOKEN_RE = re.compile(r"UIIC1-[A-Za-z0-9_-]{112}")


class LicenseCodecError(ValueError):
    """Raised when parsing or validating a license token fails."""


@dataclass(frozen=True)
class SignedLicense:
    token: str
    license_id: str
    request_code: str
    issued_date: str


@dataclass(frozen=True)
class VerifiedPayload:
    license_id: str
    fp_bytes: bytes
    fingerprint: DecodedFingerprint
    issued_date: str
    flags: int
    token: str


def generate_keypair(passphrase: str) -> Tuple[bytes, str]:
    """
    Generate a new Ed25519 keypair.
    Returns (password_encrypted_pkcs8_pem_bytes, public_key_b64).
    """
    if not passphrase or len(passphrase) < 8:
        raise ValueError("Master passphrase must be at least 8 characters long.")
    priv = Ed25519PrivateKey.generate()
    pub_raw = priv.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    priv_pem = priv.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.BestAvailableEncryption(passphrase.encode("utf-8")),
    )
    pub_b64 = base64.b64encode(pub_raw).decode("ascii")
    return priv_pem, pub_b64


def load_private_key(pem_bytes: bytes, passphrase: str) -> Ed25519PrivateKey:
    """Load an encrypted Ed25519 private key PEM using the master passphrase."""
    if not passphrase:
        raise ValueError("Master passphrase is required.")
    key = serialization.load_pem_private_key(
        pem_bytes, password=passphrase.encode("utf-8")
    )
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("Loaded key is not an Ed25519 private key.")
    return key


def derive_public_key_b64(private_key: Ed25519PrivateKey) -> str:
    """Return the base64-encoded 32-byte raw Ed25519 public key."""
    pub_raw = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(pub_raw).decode("ascii")


def sign_license_token(
    request_code: str,
    private_key: Ed25519PrivateKey,
    *,
    issued_on: Optional[date] = None,
    license_id_num: Optional[int] = None,
) -> SignedLicense:
    """Sign a permanent PC-locked license token for the given 16-character Request Code."""
    decoded = decode_request_code(request_code)
    issue_date = issued_on or datetime.now(timezone.utc).date()
    day_offset = max(0, min(65535, (issue_date - EPOCH_DATE).days))

    if license_id_num is None:
        license_id_num = secrets.randbits(32) or 1
    else:
        license_id_num = int(license_id_num) & 0xFFFFFFFF
        if license_id_num == 0:
            license_id_num = 1

    payload = PAYLOAD_STRUCT.pack(
        PAYLOAD_MAGIC,
        decoded.raw_bytes,
        license_id_num,
        day_offset,
        FLAGS_PERMANENT,
    )
    signature = private_key.sign(payload)
    body_b64 = base64.urlsafe_b64encode(payload + signature).decode("ascii").rstrip("=")
    token = f"{TOKEN_PREFIX}{body_b64}"
    return SignedLicense(
        token=token,
        license_id=f"LIC-{license_id_num:08X}",
        request_code=decoded.formatted_code,
        issued_date=issue_date.isoformat(),
    )


def extract_token_string(raw_text: str) -> str:
    """
    Extract a normalized 'UIIC1-...' token from either:
      - JSON .lic file contents
      - Raw pasted WhatsApp text (including wrapped lines / surrounding text)
    """
    if not isinstance(raw_text, str):
        raise LicenseCodecError("License input is empty.")

    # Strip BOM and invisible zero-width formatting characters sometimes injected by WhatsApp/editors
    sanitized = re.sub(r"[\u200b-\u200d\ufeff\u00ad]+", "", raw_text)
    if not sanitized.strip():
        raise LicenseCodecError("License input is empty.")

    stripped = sanitized.strip()
    # 1. Try JSON .lic file wrapper
    if stripped.startswith("{"):
        try:
            obj = json.loads(stripped)
            if isinstance(obj, dict) and isinstance(obj.get("token"), str):
                stripped = obj["token"].strip()
        except Exception as exc:
            raise LicenseCodecError("Invalid .lic JSON license file.") from exc

    # 2. Collapse whitespace (handles WhatsApp multi-line wrapping cleanly)
    compact = re.sub(r"\s+", "", stripped)
    if compact.startswith(TOKEN_PREFIX) and len(compact) == len(TOKEN_PREFIX) + ENCODED_BODY_LEN:
        return compact

    # 3. Handle copied message containing extra greeting/words around the token
    # First check direct continuous token match in stripped text
    direct = _TOKEN_RE.search(stripped)
    if direct:
        return direct.group(0)

    # Also check whitespace-collapsed text in case a pasted message both wrapped AND had notes
    in_compact = _TOKEN_RE.search(compact)
    if in_compact:
        return in_compact.group(0)

    raise LicenseCodecError(
        "Invalid license key format. Expected a key starting with 'UIIC1-'."
    )


def parse_and_verify_token(
    raw_text: str, public_key_b64: Optional[str] = None
) -> VerifiedPayload:
    """
    Decode a license token/file, verify the Ed25519 signature against the
    embedded public key, and return the verified payload.
    """
    pub_key = load_ed25519_public_key(public_key_b64)
    token = extract_token_string(raw_text)
    body = token[len(TOKEN_PREFIX) :]
    if len(body) != ENCODED_BODY_LEN:
        raise LicenseCodecError("License key length is invalid.")

    try:
        raw_bin = base64.urlsafe_b64decode((body + "==").encode("ascii"))
    except Exception as exc:
        raise LicenseCodecError("License key encoding is corrupted.") from exc

    # Re-encode canonically to reject non-canonical base64 padding bits
    if len(raw_bin) != TOTAL_TOKEN_BYTES:
        raise LicenseCodecError("License key payload size is invalid.")

    payload = raw_bin[: PAYLOAD_STRUCT.size]
    signature = raw_bin[PAYLOAD_STRUCT.size :]

    try:
        pub_key.verify(signature, payload)
    except InvalidSignature as exc:
        raise LicenseCodecError(
            "License signature is invalid or key was tampered with."
        ) from exc

    magic, fp_bytes, license_id_num, day_offset, flags = PAYLOAD_STRUCT.unpack(payload)
    if magic != PAYLOAD_MAGIC:
        raise LicenseCodecError("Unsupported license payload format.")
    if flags != FLAGS_PERMANENT:
        raise LicenseCodecError("Unsupported license flags.")

    fingerprint = decode_fingerprint_bytes(fp_bytes)
    issued_date = (EPOCH_DATE + timedelta(days=day_offset)).isoformat()
    return VerifiedPayload(
        license_id=f"LIC-{license_id_num:08X}",
        fp_bytes=fp_bytes,
        fingerprint=fingerprint,
        issued_date=issued_date,
        flags=flags,
        token=token,
    )


def format_lic_file_content(signed: SignedLicense) -> str:
    """Serialize a signed license token into clean .lic file JSON."""
    data = {
        "format": LIC_FILE_FORMAT,
        "license_id": signed.license_id,
        "issued_date": signed.issued_date,
        "request_code": signed.request_code,
        "token": signed.token,
    }
    return json.dumps(data, indent=2) + "\n"
