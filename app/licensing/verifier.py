"""Offline license verification, activation persistence, and startup/runtime gates."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from app.licensing.codec import (
    LicenseCodecError,
    SignedLicense,
    VerifiedPayload,
    format_lic_file_content,
    parse_and_verify_token,
)
from app.licensing.fingerprint import (
    FingerprintError,
    build_fingerprint_bytes,
    match_fingerprints,
)
from app.licensing.public_key import PublicKeyNotConfiguredError
from app.utils import user_data_dir

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LicenseStatus:
    valid: bool
    reason: str
    message: str
    license_id: str = ""
    issued_date: str = ""
    request_code: str = ""
    matched_anchors: int = 0
    target_anchors: int = 0


class LicenseRequiredError(RuntimeError):
    """Raised when protected execution is attempted without a valid PC-locked license."""

    def __init__(self, status: LicenseStatus):
        super().__init__(status.message)
        self.status = status


def default_license_path() -> Path:
    """Canonical per-PC license file stored in writable LOCALAPPDATA (not the EXE dir)."""
    return Path(user_data_dir("license.lic"))


def is_test_bypass_active() -> bool:
    """
    Allow existing unit tests running inside pytest from Python source to execute
    without interactive licensing prompts.

    SECURITY: NEVER bypass inside a frozen PyInstaller EXE, and NEVER honor
    environment variables (like PYTEST_CURRENT_TEST) outside a real pytest import.
    """
    if getattr(sys, "frozen", False):
        return False
    return "pytest" in sys.modules


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def verify_license_token(
    raw_text: str,
    *,
    public_key_b64: Optional[str] = None,
    current_fp: Optional[bytes] = None,
) -> LicenseStatus:
    """Verify a raw key string or .lic file content against the current PC."""
    try:
        verified: VerifiedPayload = parse_and_verify_token(
            raw_text, public_key_b64=public_key_b64
        )
    except PublicKeyNotConfiguredError as exc:
        return LicenseStatus(valid=False, reason="unconfigured", message=str(exc))
    except (LicenseCodecError, FingerprintError, ValueError) as exc:
        return LicenseStatus(valid=False, reason="invalid_token", message=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error parsing license token")
        return LicenseStatus(
            valid=False, reason="error", message=f"License validation error: {exc}"
        )

    try:
        local_fp = build_fingerprint_bytes() if current_fp is None else current_fp
    except FingerprintError as exc:
        return LicenseStatus(
            valid=False,
            reason="fingerprint_unavailable",
            message=f"Could not read this PC's hardware identifiers: {exc}",
        )

    match = match_fingerprints(verified.fp_bytes, local_fp)
    if not match.matched:
        return LicenseStatus(
            valid=False,
            reason="hardware_mismatch",
            message=(
                "This license key belongs to a different PC (or major hardware has changed). "
                "Please copy this PC's Request Code and ask for a license for this computer."
            ),
            license_id=verified.license_id,
            issued_date=verified.issued_date,
            request_code=verified.fingerprint.formatted_code,
            matched_anchors=len(match.matched_anchors),
            target_anchors=match.target_count,
        )

    return LicenseStatus(
        valid=True,
        reason="ok",
        message=f"Activated permanently ({verified.license_id})",
        license_id=verified.license_id,
        issued_date=verified.issued_date,
        request_code=verified.fingerprint.formatted_code,
        matched_anchors=len(match.matched_anchors),
        target_anchors=match.target_count,
    )


def verify_stored_license(
    *,
    license_path: Optional[Path] = None,
    public_key_b64: Optional[str] = None,
    current_fp: Optional[bytes] = None,
) -> LicenseStatus:
    """Read and verify the locally stored license.lic against this PC."""
    path = Path(license_path) if license_path else default_license_path()
    if not path.is_file():
        return LicenseStatus(
            valid=False,
            reason="missing",
            message="No license found on this PC. Please activate using your license key.",
        )
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return LicenseStatus(
            valid=False,
            reason="unreadable",
            message=f"Could not read license file: {exc}",
        )
    return verify_license_token(
        raw_text, public_key_b64=public_key_b64, current_fp=current_fp
    )


def activate_license(
    raw_text: str,
    *,
    license_path: Optional[Path] = None,
    public_key_b64: Optional[str] = None,
    current_fp: Optional[bytes] = None,
) -> LicenseStatus:
    """
    Validate a pasted license key or .lic file contents against this PC.
    Only writes license.lic if signature and machine fingerprint both pass.
    """
    status = verify_license_token(
        raw_text, public_key_b64=public_key_b64, current_fp=current_fp
    )
    if not status.valid:
        return status

    verified = parse_and_verify_token(raw_text, public_key_b64=public_key_b64)
    lic_content = format_lic_file_content(
        SignedLicense(
            token=verified.token,
            license_id=verified.license_id,
            request_code=verified.fingerprint.formatted_code,
            issued_date=verified.issued_date,
        )
    )
    dest = Path(license_path) if license_path else default_license_path()
    _atomic_write_text(dest, lic_content)
    logger.info("License activated and saved to %s (%s)", dest, verified.license_id)
    return status


def activate_from_file(
    source_file: str | Path,
    *,
    license_path: Optional[Path] = None,
    public_key_b64: Optional[str] = None,
    current_fp: Optional[bytes] = None,
) -> LicenseStatus:
    """Read a user-selected .lic or .txt license file, verify it, and activate."""
    src = Path(source_file)
    if not src.is_file():
        return LicenseStatus(
            valid=False, reason="file_not_found", message=f"File not found: {src}"
        )
    try:
        raw_text = src.read_text(encoding="utf-8")
    except OSError as exc:
        return LicenseStatus(
            valid=False, reason="unreadable", message=f"Cannot read selected file: {exc}"
        )
    return activate_license(
        raw_text,
        license_path=license_path,
        public_key_b64=public_key_b64,
        current_fp=current_fp,
    )


def require_valid_license(
    *,
    force: bool = False,
    license_path: Optional[Path] = None,
    public_key_b64: Optional[str] = None,
    current_fp: Optional[bytes] = None,
) -> LicenseStatus:
    """
    Non-GUI license enforcement gate (used by headless workers and automation engine).
    Raises LicenseRequiredError if invalid.
    """
    if not force and is_test_bypass_active():
        return LicenseStatus(
            valid=True,
            reason="pytest_bypass",
            message="Automated test environment bypass active.",
            license_id="LIC-PYTEST",
        )
    status = verify_stored_license(
        license_path=license_path,
        public_key_b64=public_key_b64,
        current_fp=current_fp,
    )
    if not status.valid:
        raise LicenseRequiredError(status)
    return status
