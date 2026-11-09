"""
Owner license vault, Windows DPAPI auto-unlock, PIN lock, and encrypted .uikey transfer bundles.

Used by:
  - tools/owner_generator_app.py (standalone GUI EXE for the non-technical Software Owner)
  - tools/license_generator.py --dev (Developer CLI to export OwnerKey.uikey setup files)

Never imported by app/ and never bundled into UIIC_Surveyor_Automation.exe.
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import json
import os
import secrets
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from app.licensing.codec import SignedLicense, derive_public_key_b64, sign_license_token
from app.licensing.public_key import PUBLIC_KEY_B64, is_public_key_configured

UIKEY_FORMAT = "uiic-owner-key-v1"
OWNER_VAULT_FORMAT = "uiic-owner-vault-v1"
_BUNDLE_AAD = b"UIIC-OWNER-KEY-V1"
_PIN_VAULT_AAD = b"UIIC-OWNER-VAULT-PIN-V1"


def default_owner_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "UIIC_License_Issuer"


def _atomic_write_text(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def _derive_key(secret: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=2**14, r=8, p=1)
    return kdf.derive(secret.encode("utf-8"))


# ── Windows DPAPI via ctypes (zero pywin32 dependency) ───────────────────────


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def is_dpapi_supported() -> bool:
    return sys.platform == "win32"


def _dpapi_bindings():
    crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    crypt_protect = ctypes.WINFUNCTYPE(
        wt.BOOL,
        ctypes.POINTER(_DATA_BLOB),
        wt.LPCWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    )(("CryptProtectData", crypt32))

    crypt_unprotect = ctypes.WINFUNCTYPE(
        wt.BOOL,
        ctypes.POINTER(_DATA_BLOB),
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wt.DWORD,
        ctypes.POINTER(_DATA_BLOB),
    )(("CryptUnprotectData", crypt32))

    local_free = ctypes.WINFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(
        ("LocalFree", kernel32)
    )
    return crypt_protect, crypt_unprotect, local_free


def dpapi_protect(plaintext: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Windows auto-unlock (DPAPI) is only supported on Windows.")
    crypt_protect, _, local_free = _dpapi_bindings()
    buf = (ctypes.c_byte * len(plaintext))(*plaintext)
    in_blob = _DATA_BLOB(len(plaintext), buf)
    out_blob = _DATA_BLOB()
    if not crypt_protect(
        ctypes.byref(in_blob),
        "UIIC Owner License Key",
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        local_free(out_blob.pbData)


def dpapi_unprotect(ciphertext: bytes) -> bytes:
    if sys.platform != "win32":
        raise RuntimeError("Windows auto-unlock (DPAPI) is only supported on Windows.")
    _, crypt_unprotect, local_free = _dpapi_bindings()
    buf = (ctypes.c_byte * len(ciphertext))(*ciphertext)
    in_blob = _DATA_BLOB(len(ciphertext), buf)
    out_blob = _DATA_BLOB()
    if not crypt_unprotect(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(out_blob),
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        local_free(out_blob.pbData)


# ── Encrypted .uikey Transfer Bundle (Freelancer -> Owner) ───────────────────


def export_owner_bundle(
    private_key: Ed25519PrivateKey,
    setup_code: str,
    dest_path: Path,
) -> Path:
    """
    Package an Ed25519 signing key into an encrypted OwnerKey.uikey file
    protected by a simple Setup Code shared with the software owner.
    """
    clean_code = (setup_code or "").strip()
    if len(clean_code) < 4:
        raise ValueError("Setup Code must be at least 4 characters or digits.")

    raw32 = private_key.private_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PrivateFormat.Raw,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_b64 = derive_public_key_b64(private_key)
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(12)
    aes_key = _derive_key(clean_code, salt)
    ciphertext = AESGCM(aes_key).encrypt(nonce, raw32, _BUNDLE_AAD)

    payload = {
        "format": UIKEY_FORMAT,
        "created_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "public_key_b64": pub_b64,
        "salt_b64": base64.b64encode(salt).decode("ascii"),
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(ciphertext).decode("ascii"),
    }
    dest = Path(dest_path)
    _atomic_write_text(dest, json.dumps(payload, indent=2) + "\n")
    return dest


def decrypt_owner_bundle(
    bundle_path: Path,
    setup_code: str,
    *,
    expected_public_key_b64: Optional[str] = None,
) -> Tuple[Ed25519PrivateKey, str]:
    """Read and decrypt an OwnerKey.uikey setup file using the Setup Code."""
    path = Path(bundle_path)
    if not path.is_file():
        raise FileNotFoundError("The selected key file could not be found.")
    clean_code = (setup_code or "").strip()
    if not clean_code:
        raise ValueError("Please enter the Setup Code sent by your developer.")

    try:
        obj = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError("The selected file is not a valid Setup Key file (.uikey).") from exc

    if not isinstance(obj, dict) or obj.get("format") != UIKEY_FORMAT:
        raise ValueError("Unsupported Setup Key file format.")

    try:
        salt = base64.b64decode(obj["salt_b64"].encode("ascii"))
        nonce = base64.b64decode(obj["nonce_b64"].encode("ascii"))
        ciphertext = base64.b64decode(obj["ciphertext_b64"].encode("ascii"))
    except Exception as exc:
        raise ValueError("The Setup Key file appears damaged.") from exc

    try:
        aes_key = _derive_key(clean_code, salt)
        raw32 = AESGCM(aes_key).decrypt(nonce, ciphertext, _BUNDLE_AAD)
    except InvalidTag as exc:
        raise ValueError("Wrong Setup Code. Please check the code from your developer.") from exc

    if len(raw32) != 32:
        raise ValueError("Setup Key file contains an invalid key length.")

    priv = Ed25519PrivateKey.from_private_bytes(raw32)
    pub_b64 = derive_public_key_b64(priv)
    if obj.get("public_key_b64") and obj["public_key_b64"] != pub_b64:
        raise ValueError("Setup Key file failed consistency check.")

    expected = PUBLIC_KEY_B64 if expected_public_key_b64 is None else expected_public_key_b64
    if is_public_key_configured(expected) and expected.strip() != pub_b64:
        raise ValueError(
            "This Setup Key file does not match this version of UIIC Surveyor Automation. "
            "Please ask your developer for the matching OwnerKey.uikey file."
        )
    return priv, pub_b64


# ── Local Owner Vault (Auto-unlock via Windows DPAPI OR Optional PIN) ────────


class OwnerVault:
    """Simple owner-side storage that keeps signing keys protected and jargon-free."""

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        *,
        expected_public_key_b64: Optional[str] = None,
    ):
        self.data_dir = Path(data_dir) if data_dir else default_owner_dir()
        self.expected_public_key_b64 = expected_public_key_b64

    @property
    def vault_path(self) -> Path:
        return self.data_dir / "owner_vault.json"

    @property
    def history_path(self) -> Path:
        return self.data_dir / "issued_licenses.jsonl"

    def has_vault(self) -> bool:
        return self.vault_path.is_file()

    def _read_vault_obj(self) -> Dict[str, str]:
        obj = json.loads(self.vault_path.read_text(encoding="utf-8"))
        if not isinstance(obj, dict) or obj.get("format") != OWNER_VAULT_FORMAT:
            raise ValueError("Saved license key data is invalid or damaged.")
        return obj

    def unlock_mode(self) -> Optional[str]:
        if not self.has_vault():
            return None
        try:
            mode = self._read_vault_obj().get("unlock_mode")
            return mode if mode in ("dpapi", "pin") else None
        except Exception:
            return None

    @staticmethod
    def find_nearby_uikey(search_dirs: Optional[List[Path]] = None) -> Optional[Path]:
        """Auto-detect OwnerKey.uikey placed next to the EXE or in current folder."""
        dirs: List[Path] = list(search_dirs) if search_dirs is not None else []
        if not dirs:
            if getattr(sys, "frozen", False):
                dirs.append(Path(sys.executable).resolve().parent)
            dirs.append(Path.cwd())

        for directory in dirs:
            if not directory or not directory.is_dir():
                continue
            preferred = directory / "OwnerKey.uikey"
            if preferred.is_file():
                return preferred
            candidates = sorted(directory.glob("*.uikey"))
            if len(candidates) == 1:
                return candidates[0]
        return None

    def _save_private_key(self, private_key: Ed25519PrivateKey, unlock_mode: str, pin: str = "") -> None:
        if unlock_mode not in ("dpapi", "pin"):
            raise ValueError("Invalid unlock option.")

        raw32 = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        pub_b64 = derive_public_key_b64(private_key)

        record: Dict[str, str] = {
            "format": OWNER_VAULT_FORMAT,
            "unlock_mode": unlock_mode,
            "public_key_b64": pub_b64,
            "updated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        }

        if unlock_mode == "dpapi":
            protected = dpapi_protect(raw32)
            record["dpapi_b64"] = base64.b64encode(protected).decode("ascii")
        else:
            clean_pin = (pin or "").strip()
            if len(clean_pin) < 4:
                raise ValueError("PIN must be at least 4 characters or digits.")
            salt = secrets.token_bytes(16)
            nonce = secrets.token_bytes(12)
            aes_key = _derive_key(clean_pin, salt)
            ciphertext = AESGCM(aes_key).encrypt(nonce, raw32, _PIN_VAULT_AAD)
            record["salt_b64"] = base64.b64encode(salt).decode("ascii")
            record["nonce_b64"] = base64.b64encode(nonce).decode("ascii")
            record["ciphertext_b64"] = base64.b64encode(ciphertext).decode("ascii")

        _atomic_write_text(self.vault_path, json.dumps(record, indent=2) + "\n")

    def import_uikey_and_save(
        self,
        bundle_path: Path,
        setup_code: str,
        *,
        unlock_mode: str = "dpapi",
        pin: str = "",
        confirm_pin: Optional[str] = None,
    ) -> Ed25519PrivateKey:
        if unlock_mode == "pin":
            clean_pin = (pin or "").strip()
            if len(clean_pin) < 4:
                raise ValueError("PIN must be at least 4 characters or digits.")
            if confirm_pin is not None and clean_pin != confirm_pin.strip():
                raise ValueError("PINs do not match.")

        priv, _ = decrypt_owner_bundle(
            bundle_path,
            setup_code,
            expected_public_key_b64=self.expected_public_key_b64,
        )
        self._save_private_key(priv, unlock_mode=unlock_mode, pin=pin)
        return priv

    def auto_unlock(self) -> Optional[Ed25519PrivateKey]:
        """
        If configured for Windows auto-unlock, return the signing key automatically.
        Returns None if configured for PIN unlock (caller prompts for PIN).
        """
        if not self.has_vault():
            return None
        obj = self._read_vault_obj()
        mode = obj.get("unlock_mode")
        if mode == "pin":
            return None
        if mode != "dpapi":
            raise ValueError("Unsupported saved unlock mode.")

        try:
            protected = base64.b64decode(obj["dpapi_b64"].encode("ascii"))
            raw32 = dpapi_unprotect(protected)
            if len(raw32) != 32:
                raise ValueError("Invalid key length.")
            return Ed25519PrivateKey.from_private_bytes(raw32)
        except Exception as exc:
            raise ValueError(
                "Could not unlock automatically on this Windows user account. "
                "Please re-import your OwnerKey.uikey file."
            ) from exc

    def unlock_with_pin(self, pin: str) -> Ed25519PrivateKey:
        clean_pin = (pin or "").strip()
        if not clean_pin:
            raise ValueError("Please enter your PIN.")
        obj = self._read_vault_obj()
        if obj.get("unlock_mode") != "pin":
            raise ValueError("This tool is set to auto-unlock mode.")
        try:
            salt = base64.b64decode(obj["salt_b64"].encode("ascii"))
            nonce = base64.b64decode(obj["nonce_b64"].encode("ascii"))
            ciphertext = base64.b64decode(obj["ciphertext_b64"].encode("ascii"))
            raw32 = AESGCM(_derive_key(clean_pin, salt)).decrypt(
                nonce, ciphertext, _PIN_VAULT_AAD
            )
            return Ed25519PrivateKey.from_private_bytes(raw32)
        except InvalidTag as exc:
            raise ValueError("Wrong PIN. Please try again.") from exc
        except Exception as exc:
            raise ValueError("Could not read saved key with that PIN.") from exc

    def change_unlock_mode(
        self,
        private_key: Ed25519PrivateKey,
        new_mode: str,
        *,
        pin: str = "",
        confirm_pin: Optional[str] = None,
    ) -> None:
        if new_mode == "pin":
            clean_pin = (pin or "").strip()
            if len(clean_pin) < 4:
                raise ValueError("PIN must be at least 4 characters or digits.")
            if confirm_pin is not None and clean_pin != confirm_pin.strip():
                raise ValueError("PINs do not match.")
        self._save_private_key(private_key, unlock_mode=new_mode, pin=pin)

    def reset_vault(self) -> None:
        if self.vault_path.is_file():
            self.vault_path.unlink()

    def issue_license(
        self,
        private_key: Ed25519PrivateKey,
        friend_name: str,
        request_code: str,
    ) -> SignedLicense:
        clean_name = (friend_name or "").strip()
        if not clean_name:
            raise ValueError("Please enter your friend's name first.")
        signed = sign_license_token(request_code, private_key)
        record = {
            "issued_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "issued_date": signed.issued_date,
            "friend_name": clean_name,
            "request_code": signed.request_code,
            "license_id": signed.license_id,
            "token_prefix": signed.token[:22] + "...",
            "token": signed.token,
        }
        self.data_dir.mkdir(parents=True, exist_ok=True)
        with self.history_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return signed

    def load_history(self) -> List[Dict[str, str]]:
        if not self.history_path.is_file():
            return []
        rows: List[Dict[str, str]] = []
        for line in self.history_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                if isinstance(obj, dict):
                    rows.append(obj)
            except Exception:
                continue
        rows.reverse()
        return rows
