"""
Windows machine fingerprinting and 16-character Crockford Base32 Request Code.

Uses native Win32 APIs and Registry directly (no admin privileges, no wmic.exe,
no subprocesses, no MAC addresses) so it remains fast and reliable on Windows 10
and Windows 11 24H2+.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import hashlib
import hmac
import logging
import os
import re
import struct
import sys
from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

logger = logging.getLogger(__name__)

FINGERPRINT_VERSION = 1
APP_FINGERPRINT_SALT = b"UIIC_SURVEYOR_AUTOMATION_PC_LOCK_V1"
CHECK_CONTEXT = b"UIIC-REQ-CHK-V1"

# Crockford Base32 omits confusing characters (I, L, O, U)
CROCKFORD_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_CROCKFORD_ENCODE = {i: ch for i, ch in enumerate(CROCKFORD_ALPHABET)}
_CROCKFORD_DECODE = {ch: i for i, ch in enumerate(CROCKFORD_ALPHABET)}
_CROCKFORD_DECODE.update({"O": 0, "I": 1, "L": 1})

ANCHOR_ORDER: Tuple[str, ...] = (
    "machine_guid",
    "smbios_uuid",
    "disk_serial",
    "volume_serial",
)

ANCHOR_MACHINE_GUID = 0
ANCHOR_SMBIOS_UUID = 1
ANCHOR_DISK_SERIAL = 2
ANCHOR_VOLUME_SERIAL = 3

_PLACEHOLDER_SUBSTRINGS = (
    "TO BE FILLED",
    "DEFAULT STRING",
    "NOT SPECIFIED",
    "NOT AVAILABLE",
    "SYSTEM SERIAL",
    "CHASSIS SERIAL",
    "BASE BOARD",
    "ASSET TAG",
    "INVALID",
    "EVALUATION",
    "SYS-123456",
    "1234567890",
    "0123456789",
)
_PLACEHOLDER_EXACT = {
    "",
    "NONE",
    "NULL",
    "NA",
    "N/A",
    "TBD",
    "UNKNOWN",
    "OEM",
    "STANDARD",
    "SERIAL",
    "UUID",
}


class FingerprintError(RuntimeError):
    """Raised when a valid hardware fingerprint cannot be collected or decoded."""


@dataclass(frozen=True)
class DecodedFingerprint:
    raw_bytes: bytes
    version: int
    present_mask: int
    digests: Tuple[bytes, bytes, bytes, bytes]
    formatted_code: str


@dataclass(frozen=True)
class FingerprintMatchResult:
    matched: bool
    matched_anchors: Tuple[int, ...]
    comparable_count: int
    target_count: int
    reason: str


def _popcount4(mask: int) -> int:
    return bin(mask & 0x0F).count("1")


def normalize_anchor_value(anchor_name: str, raw_value: Optional[str]) -> Optional[str]:
    """
    Normalize a raw Windows hardware/OS identifier and reject known OEM/VM junk.
    Returns canonical uppercase string or None if unusable/placeholder.
    """
    if raw_value is None:
        return None
    text = str(raw_value).strip().strip("{}").strip()
    if not text:
        return None
    collapsed = re.sub(r"\s+", " ", text).upper()
    if collapsed in _PLACEHOLDER_EXACT:
        return None
    for marker in _PLACEHOLDER_SUBSTRINGS:
        if marker in collapsed:
            return None

    compact = re.sub(r"[^A-Z0-9]", "", collapsed)
    if len(compact) < 4:
        return None
    # Reject all-same character strings like 00000000..., FFFFFFFF..., AAAAAAAA...
    if len(set(compact)) <= 1:
        return None

    if anchor_name in ("machine_guid", "smbios_uuid", "volume_serial", "disk_serial"):
        return compact
    return collapsed


def _digest_anchor(anchor_name: str, canonical_value: str) -> bytes:
    msg = f"{anchor_name}:{canonical_value}".encode("utf-8")
    return hmac.new(APP_FINGERPRINT_SALT, msg, hashlib.sha256).digest()[:2]


# ── Pure parsers (unit-testable offline without Win32 calls) ──────────────────


def parse_smbios_type1_uuid(raw_rsmb: bytes) -> Optional[str]:
    """
    Parse raw SMBIOS data returned by GetSystemFirmwareTable('RSMB', 0)
    and return the Type 1 (System Information) 16-byte UUID as 32 uppercase hex chars.
    """
    if not raw_rsmb or len(raw_rsmb) < 12:
        return None
    # RawSMBIOSData header: Used20CallingMethod(1), Major(1), Minor(1), DmiRev(1), Length(4)
    pos = 8
    limit = len(raw_rsmb)
    while pos + 4 <= limit:
        stype = raw_rsmb[pos]
        slen = raw_rsmb[pos + 1]
        if slen < 4 or pos + slen > limit:
            break
        if stype == 1 and slen >= 0x18:
            uuid_bytes = raw_rsmb[pos + 8 : pos + 24]
            return uuid_bytes.hex().upper()
        if stype == 127:  # End-of-table
            break
        # Advance past formatted struct + double-null terminated string section
        spos = pos + slen
        while spos + 1 < limit and not (raw_rsmb[spos] == 0 and raw_rsmb[spos + 1] == 0):
            spos += 1
        pos = spos + 2
    return None


def parse_storage_device_serial(raw_desc: bytes) -> Optional[str]:
    """
    Parse STORAGE_DEVICE_DESCRIPTOR returned by IOCTL_STORAGE_QUERY_PROPERTY
    and extract the serial number C-string if valid.
    """
    # Need at least up to SerialNumberOffset (offset 24 + 4 bytes = 28 bytes)
    if not raw_desc or len(raw_desc) < 28:
        return None
    serial_offset = struct.unpack_from("<I", raw_desc, 24)[0]
    if serial_offset == 0 or serial_offset >= len(raw_desc):
        return None
    end = raw_desc.find(b"\x00", serial_offset)
    if end == -1:
        end = len(raw_desc)
    try:
        return raw_desc[serial_offset:end].decode("ascii", errors="ignore").strip()
    except Exception:
        return None


# ── Native Windows Anchor Collectors (zero subprocess, zero admin needed) ─────


def _get_system_drive() -> str:
    drive = (os.environ.get("SystemDrive") or "C:").strip().rstrip("\\/")
    if len(drive) == 1:
        drive += ":"
    return drive or "C:"


def _read_machine_guid() -> Optional[str]:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        access = winreg.KEY_READ | getattr(winreg, "KEY_WOW64_64KEY", 0)
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
            0,
            access,
        ) as key:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
            return str(val) if val else None
    except Exception as exc:
        logger.debug("MachineGuid lookup failed: %s", exc)
        return None


def _win32_funcs():
    """Return 64-bit-safe WINFUNCTYPE bindings without mutating global ctypes.windll.kernel32."""
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    create_file = ctypes.WINFUNCTYPE(
        wintypes.HANDLE,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    )(("CreateFileW", k32))

    device_io = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    )(("DeviceIoControl", k32))

    close_handle = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE)(("CloseHandle", k32))

    get_firmware_table = ctypes.WINFUNCTYPE(
        wintypes.UINT,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    )(("GetSystemFirmwareTable", k32))

    get_volume_info = ctypes.WINFUNCTYPE(
        wintypes.BOOL,
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPWSTR,
        wintypes.DWORD,
    )(("GetVolumeInformationW", k32))

    return create_file, device_io, close_handle, get_firmware_table, get_volume_info


def _read_smbios_uuid() -> Optional[str]:
    if sys.platform != "win32":
        return None
    try:
        _, _, _, get_firmware_table, _ = _win32_funcs()
        sig = int.from_bytes(b"RSMB", "big")
        size = get_firmware_table(sig, 0, None, 0)
        if size < 12 or size > 4 * 1024 * 1024:
            return None
        buf = ctypes.create_string_buffer(size)
        written = get_firmware_table(sig, 0, buf, size)
        if written < 12:
            return None
        return parse_smbios_type1_uuid(buf.raw[:written])
    except Exception as exc:
        logger.debug("SMBIOS UUID lookup failed: %s", exc)
        return None


def _read_boot_disk_serial() -> Optional[str]:
    if sys.platform != "win32":
        return None

    class _StoragePropertyQuery(ctypes.Structure):
        _fields_ = [
            ("PropertyId", wintypes.DWORD),
            ("QueryType", wintypes.DWORD),
            ("AdditionalParameters", ctypes.c_byte * 1),
        ]

    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value
    FILE_SHARE_RW = 0x00000001 | 0x00000002
    OPEN_EXISTING = 3
    IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS = 0x00560000
    IOCTL_STORAGE_QUERY_PROPERTY = 0x002D1400

    try:
        create_file, device_io, close_handle, _, _ = _win32_funcs()
        disk_num = 0
        sys_drive = _get_system_drive()
        hv = create_file(f"\\\\.\\{sys_drive}", 0, FILE_SHARE_RW, None, OPEN_EXISTING, 0, None)
        if hv and hv != INVALID_HANDLE_VALUE:
            try:
                vbuf = ctypes.create_string_buffer(512)
                vret = wintypes.DWORD()
                if device_io(
                    hv,
                    IOCTL_VOLUME_GET_VOLUME_DISK_EXTENTS,
                    None,
                    0,
                    vbuf,
                    len(vbuf),
                    ctypes.byref(vret),
                    None,
                ):
                    if vret.value >= 12:
                        extents = struct.unpack_from("<I", vbuf.raw, 0)[0]
                        if extents >= 1:
                            disk_num = struct.unpack_from("<I", vbuf.raw, 8)[0]
            finally:
                close_handle(hv)

        hd = create_file(
            f"\\\\.\\PhysicalDrive{disk_num}",
            0,
            FILE_SHARE_RW,
            None,
            OPEN_EXISTING,
            0,
            None,
        )
        if not hd or hd == INVALID_HANDLE_VALUE:
            return None
        try:
            query = _StoragePropertyQuery(0, 0)
            dbuf = ctypes.create_string_buffer(4096)
            dret = wintypes.DWORD()
            if not device_io(
                hd,
                IOCTL_STORAGE_QUERY_PROPERTY,
                ctypes.byref(query),
                ctypes.sizeof(query),
                dbuf,
                len(dbuf),
                ctypes.byref(dret),
                None,
            ):
                return None
            return parse_storage_device_serial(dbuf.raw[: dret.value])
        finally:
            close_handle(hd)
    except Exception as exc:
        logger.debug("Physical disk serial lookup failed: %s", exc)
        return None


def _read_volume_serial() -> Optional[str]:
    if sys.platform != "win32":
        return None
    try:
        _, _, _, _, get_volume_info = _win32_funcs()
        serial = wintypes.DWORD()
        root_path = _get_system_drive() + "\\"
        ok = get_volume_info(root_path, None, 0, ctypes.byref(serial), None, None, None, 0)
        if not ok or serial.value == 0:
            return None
        return f"{serial.value:08X}"
    except Exception as exc:
        logger.debug("Volume serial lookup failed: %s", exc)
        return None


def collect_raw_anchors() -> Dict[str, Optional[str]]:
    """Collect the 4 Windows machine anchors safely."""
    return {
        "machine_guid": _read_machine_guid(),
        "smbios_uuid": _read_smbios_uuid(),
        "disk_serial": _read_boot_disk_serial(),
        "volume_serial": _read_volume_serial(),
    }


# ── Bit-Packing & Crockford Base32 Codec ─────────────────────────────────────


def build_fingerprint_bytes(anchors: Optional[Mapping[str, Optional[str]]] = None) -> bytes:
    """
    Build the 10-byte machine fingerprint from raw or live Windows anchors.

    Layout (10 bytes = 80 bits):
      - Byte 0:     (version << 4) | present_mask (bits 0..3 for ANCHOR_ORDER)
      - Bytes 1..2: 16-bit HMAC-SHA256 digest of machine_guid (0x0000 if absent)
      - Bytes 3..4: 16-bit HMAC-SHA256 digest of smbios_uuid  (0x0000 if absent)
      - Bytes 5..6: 16-bit HMAC-SHA256 digest of disk_serial  (0x0000 if absent)
      - Bytes 7..8: 16-bit HMAC-SHA256 digest of volume_serial(0x0000 if absent)
      - Byte 9:     1-byte typo/integrity check over bytes 0..8
    """
    source = collect_raw_anchors() if anchors is None else anchors
    present_mask = 0
    chunks = []
    for idx, name in enumerate(ANCHOR_ORDER):
        canon = normalize_anchor_value(name, source.get(name))
        if canon is not None:
            present_mask |= 1 << idx
            chunks.append(_digest_anchor(name, canon))
        else:
            chunks.append(b"\x00\x00")

    if _popcount4(present_mask) < 2:
        raise FingerprintError(
            "Unable to gather at least 2 distinct Windows machine identifiers on this PC."
        )

    header = ((FINGERPRINT_VERSION & 0x0F) << 4) | (present_mask & 0x0F)
    raw9 = bytes([header]) + b"".join(chunks)
    chk = hashlib.sha256(CHECK_CONTEXT + raw9).digest()[0]
    return raw9 + bytes([chk])


def encode_request_code(fp_bytes: bytes) -> str:
    """Encode a 10-byte fingerprint as 'XXXX-XXXX-XXXX-XXXX' (16 Crockford Base32 chars)."""
    if len(fp_bytes) != 10:
        raise ValueError(f"Fingerprint must be 10 bytes, got {len(fp_bytes)}.")
    value = int.from_bytes(fp_bytes, "big")
    chars = [_CROCKFORD_ENCODE[(value >> (5 * (15 - i))) & 0x1F] for i in range(16)]
    joined = "".join(chars)
    return f"{joined[0:4]}-{joined[4:8]}-{joined[8:12]}-{joined[12:16]}"


def decode_request_code(code: str) -> DecodedFingerprint:
    """Decode and checksum-verify a 16-character Request Code."""
    if not isinstance(code, str):
        raise FingerprintError("Request Code must be text.")
    cleaned = re.sub(r"[\s\-_]", "", code).upper()
    if len(cleaned) != 16:
        raise FingerprintError(
            f"Request Code must have 16 characters (got {len(cleaned)})."
        )
    value = 0
    for ch in cleaned:
        if ch not in _CROCKFORD_DECODE:
            raise FingerprintError(f"Invalid character '{ch}' in Request Code.")
        value = (value << 5) | _CROCKFORD_DECODE[ch]

    raw10 = value.to_bytes(10, "big")
    return decode_fingerprint_bytes(raw10)


def decode_fingerprint_bytes(raw10: bytes) -> DecodedFingerprint:
    """Validate and unpack raw 10-byte fingerprint bytes."""
    if not isinstance(raw10, (bytes, bytearray)) or len(raw10) != 10:
        raise FingerprintError("Invalid machine fingerprint length.")
    raw10 = bytes(raw10)
    version = (raw10[0] >> 4) & 0x0F
    if version != FINGERPRINT_VERSION:
        raise FingerprintError(f"Unsupported fingerprint version: {version}.")
    expected_chk = hashlib.sha256(CHECK_CONTEXT + raw10[:9]).digest()[0]
    if raw10[9] != expected_chk:
        raise FingerprintError(
            "Request Code check failed — please check for a mistyped letter or digit."
        )
    present_mask = raw10[0] & 0x0F
    if _popcount4(present_mask) < 2:
        raise FingerprintError("Request Code does not contain enough valid machine anchors.")

    digests = (
        raw10[1:3],
        raw10[3:5],
        raw10[5:7],
        raw10[7:9],
    )
    return DecodedFingerprint(
        raw_bytes=raw10,
        version=version,
        present_mask=present_mask,
        digests=digests,
        formatted_code=encode_request_code(raw10),
    )


def get_request_code(anchors: Optional[Mapping[str, Optional[str]]] = None) -> str:
    """Return this PC's 16-character Request Code ('XXXX-XXXX-XXXX-XXXX')."""
    return encode_request_code(build_fingerprint_bytes(anchors))


def match_fingerprints(target_fp: bytes, current_fp: bytes) -> FingerprintMatchResult:
    """
    Compare a license's embedded machine fingerprint against the current PC.

    Tolerance policy:
      - 4 target anchors present: match >= 3 anchors, OR match >= 2 when BOTH
        hardware anchors (SMBIOS UUID + Boot Disk Serial) match (handles clean
        Windows reinstall on the same PC/SSD).
      - 3 target anchors present: match >= 2 anchors.
      - 2 target anchors present: require both 2 of 2 anchors to match.
    """
    target = decode_fingerprint_bytes(target_fp)
    current = decode_fingerprint_bytes(current_fp)

    matched: list[int] = []
    comparable = 0
    for idx in range(4):
        t_bit = (target.present_mask >> idx) & 1
        c_bit = (current.present_mask >> idx) & 1
        if t_bit and c_bit:
            comparable += 1
            if hmac.compare_digest(target.digests[idx], current.digests[idx]):
                matched.append(idx)

    target_count = _popcount4(target.present_mask)
    matched_tuple = tuple(matched)

    if target_count >= 4:
        ok = len(matched) >= 3 or (
            len(matched) >= 2
            and ANCHOR_SMBIOS_UUID in matched
            and ANCHOR_DISK_SERIAL in matched
        )
    elif target_count == 3:
        ok = len(matched) >= 2
    elif target_count == 2:
        ok = len(matched) == 2
    else:
        ok = False

    if ok:
        reason = f"Matched {len(matched)}/{target_count} machine anchors"
    else:
        reason = (
            f"PC mismatch: matched only {len(matched)}/{target_count} machine anchors "
            f"({comparable} comparable)"
        )
    return FingerprintMatchResult(
        matched=ok,
        matched_anchors=matched_tuple,
        comparable_count=comparable,
        target_count=target_count,
        reason=reason,
    )
