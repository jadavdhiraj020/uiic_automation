"""Embedded Ed25519 public key used to verify offline license tokens."""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

KEY_VERSION = 1

# Replaced automatically when you initialize your keypair via tools/license_generator.py.
# Only the PUBLIC verification key lives here — private signing keys NEVER live in Git.
PUBLIC_KEY_B64 = "di7j12xRWsdQ4uqT1buN/cStWMfmF1UKp2+5DsRyX0s="


class PublicKeyNotConfiguredError(RuntimeError):
    """Raised when the application's public verification key has not been configured."""


def is_public_key_configured(key_b64: Optional[str] = None) -> bool:
    candidate = (PUBLIC_KEY_B64 if key_b64 is None else key_b64) or ""
    candidate = candidate.strip()
    if not candidate or candidate == "UNCONFIGURED":
        return False
    try:
        raw = base64.b64decode(candidate.encode("ascii"), validate=True)
        return len(raw) == 32
    except Exception:
        return False


def load_ed25519_public_key(key_b64: Optional[str] = None) -> Ed25519PublicKey:
    candidate = (PUBLIC_KEY_B64 if key_b64 is None else key_b64) or ""
    candidate = candidate.strip()
    if not candidate or candidate == "UNCONFIGURED":
        raise PublicKeyNotConfiguredError(
            "Licensing public key is not configured yet. "
            "Run tools/license_generator.py on your developer PC to initialize your keypair."
        )
    try:
        raw = base64.b64decode(candidate.encode("ascii"), validate=True)
    except Exception as exc:
        raise ValueError("Embedded public key is not valid base64.") from exc
    if len(raw) != 32:
        raise ValueError(f"Embedded Ed25519 public key must be 32 bytes, got {len(raw)}.")
    return Ed25519PublicKey.from_public_bytes(raw)


def update_public_key_file(
    new_public_key_b64: str, target_path: Optional[Path] = None
) -> Path:
    """
    Validate a 32-byte Ed25519 base64 public key and atomically update PUBLIC_KEY_B64
    inside public_key.py so the packaged EXE trusts licenses from that keypair.
    """
    load_ed25519_public_key(new_public_key_b64)
    path = Path(target_path) if target_path else Path(__file__).resolve()
    content = path.read_text(encoding="utf-8")
    pattern = re.compile(r'^PUBLIC_KEY_B64\s*=\s*["\'][^"\']*["\'][^\S\r\n]*$', re.MULTILINE)
    if not pattern.search(content):
        raise ValueError(f"Could not locate PUBLIC_KEY_B64 assignment in {path}")
    updated = pattern.sub(f'PUBLIC_KEY_B64 = "{new_public_key_b64.strip()}"', content, count=1)

    tmp = path.with_suffix(".py.tmp")
    tmp.write_text(updated, encoding="utf-8")
    os.replace(tmp, path)

    global PUBLIC_KEY_B64
    if target_path is None or path.resolve() == Path(__file__).resolve():
        PUBLIC_KEY_B64 = new_public_key_b64.strip()
    return path
