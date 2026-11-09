"""Comprehensive test suite for offline Ed25519 PC-locked licensing."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import struct
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

from app.automation.engine import AutomationEngine
from app.data.data_model import ClaimData
from app.licensing.codec import (
    EPOCH_DATE,
    PAYLOAD_MAGIC,
    PAYLOAD_STRUCT,
    TOKEN_PREFIX,
    extract_token_string,
    format_lic_file_content,
    generate_keypair,
    load_private_key,
    parse_and_verify_token,
    sign_license_token,
)
from app.licensing.fingerprint import (
    ANCHOR_DISK_SERIAL,
    ANCHOR_MACHINE_GUID,
    ANCHOR_SMBIOS_UUID,
    ANCHOR_VOLUME_SERIAL,
    CHECK_CONTEXT,
    CROCKFORD_ALPHABET,
    FingerprintError,
    build_fingerprint_bytes,
    collect_raw_anchors,
    decode_fingerprint_bytes,
    decode_request_code,
    encode_request_code,
    get_request_code,
    match_fingerprints,
    normalize_anchor_value,
    parse_smbios_type1_uuid,
    parse_storage_device_serial,
)
from app.licensing.public_key import (
    PUBLIC_KEY_B64,
    PublicKeyNotConfiguredError,
    is_public_key_configured,
    load_ed25519_public_key,
    update_public_key_file,
)
from app.licensing.verifier import (
    LicenseRequiredError,
    LicenseStatus,
    activate_from_file,
    activate_license,
    is_test_bypass_active,
    require_valid_license,
    verify_license_token,
    verify_stored_license,
)

REPO_ROOT = Path(__file__).resolve().parent.parent

PC_A_ANCHORS = {
    "machine_guid": "11111111-2222-3333-4444-555555555555",
    "smbios_uuid": "AABBCCDDEEFF00112233445566778899",
    "disk_serial": "WD-WCC6Y7AA1234",
    "volume_serial": "9A8B7C6D",
}

PC_B_ANCHORS = {
    "machine_guid": "99999999-8888-7777-6666-111111111111",
    "smbios_uuid": "00112233445566778899AABBCCDDEEFF",
    "disk_serial": "S6E2NS0T999999",
    "volume_serial": "12345678",
}


@pytest.fixture
def qapp():
    try:
        from PyQt6.QtWidgets import QApplication
    except ImportError as exc:
        pytest.skip(f"PyQt6.QtWidgets unavailable on this host: {exc}")

    return QApplication.instance() or QApplication([])


@pytest.fixture
def keypair():
    pem_bytes, pub_b64 = generate_keypair("StrongMasterPass!2026")
    priv = load_private_key(pem_bytes, "StrongMasterPass!2026")
    return pem_bytes, priv, pub_b64


# ── 1. Fingerprint & Crockford Base32 ────────────────────────────────────────


class TestFingerprint:
    @pytest.mark.skipif(sys.platform != "win32", reason="Windows-only anchor collection")
    def test_live_windows_request_code_smoke(self):
        anchors = collect_raw_anchors()
        assert isinstance(anchors, dict)
        valid_count = sum(
            1 for k, v in anchors.items() if normalize_anchor_value(k, v) is not None
        )
        assert valid_count >= 2

        fp = build_fingerprint_bytes()
        assert len(fp) == 10

        code = get_request_code()
        assert re.fullmatch(
            r"[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}-"
            r"[0-9A-HJKMNP-TV-Z]{4}-[0-9A-HJKMNP-TV-Z]{4}",
            code,
        )
        for forbidden in ("I", "L", "O", "U"):
            assert forbidden not in code

        decoded = decode_request_code(code)
        assert decoded.raw_bytes == fp
        assert decoded.formatted_code == code

    def test_crockford_normalization_and_lookalike_recovery(self):
        code = get_request_code(PC_A_ANCHORS)
        assert decode_request_code(code).formatted_code == code

        # Lowercase, spaces, underscores, stripped hyphens
        messed = "  " + code.lower().replace("-", " ") + "\n"
        assert decode_request_code(messed).formatted_code == code
        assert decode_request_code(code.replace("-", "_")).formatted_code == code
        assert decode_request_code(code.replace("-", "")).formatted_code == code

        # Confusing Crockford chars: O->0, I/L->1 (using synthetic raw10 guaranteeing 0 and 1 appear)
        raw9 = bytes([0x1F, 0x00, 0x42, 0x12, 0x34, 0x56, 0x78, 0x9A, 0xBC])
        import hashlib

        raw10 = raw9 + bytes([hashlib.sha256(CHECK_CONTEXT + raw9).digest()[0]])
        base_code = encode_request_code(raw10)
        lookalike = base_code.replace("0", "o").replace("1", "i")
        assert decode_request_code(lookalike).raw_bytes == raw10
        lookalike_l = base_code.replace("0", "O").replace("1", "l")
        assert decode_request_code(lookalike_l).raw_bytes == raw10

    def test_typo_check_byte_catches_every_single_char_mistype(self):
        code = get_request_code(PC_A_ANCHORS)
        compact = code.replace("-", "")
        assert len(compact) == 16

        for pos in range(16):
            orig_ch = compact[pos]
            alt_idx = (CROCKFORD_ALPHABET.index(orig_ch) + 1) % len(CROCKFORD_ALPHABET)
            mutated = compact[:pos] + CROCKFORD_ALPHABET[alt_idx] + compact[pos + 1 :]
            with pytest.raises(FingerprintError):
                decode_request_code(mutated)

    @pytest.mark.parametrize(
        "bad_code",
        [
            "",
            "   ",
            None,
            12345,
            "ABCD-EFGH-IJKL",
            "ABCD-EFGH-JKLM-NPQR-S",
            "UUUU-UUUU-UUUU-UUUU",
            "AAAA-AAAA-AAAA-AAAB",
        ],
    )
    def test_invalid_request_codes_rejected(self, bad_code):
        with pytest.raises(FingerprintError):
            decode_request_code(bad_code)

    def test_reject_wrong_version_and_insufficient_anchor_mask(self):
        import hashlib

        # Version 2
        raw9_v2 = bytes([0x2F, 1, 2, 3, 4, 5, 6, 7, 8])
        chk_v2 = hashlib.sha256(CHECK_CONTEXT + raw9_v2).digest()[0]
        with pytest.raises(FingerprintError, match="version"):
            decode_fingerprint_bytes(raw9_v2 + bytes([chk_v2]))

        # Only 1 anchor bit set
        raw9_one = bytes([0x11, 1, 2, 0, 0, 0, 0, 0, 0])
        chk_one = hashlib.sha256(CHECK_CONTEXT + raw9_one).digest()[0]
        with pytest.raises(FingerprintError, match="enough valid"):
            decode_fingerprint_bytes(raw9_one + bytes([chk_one]))

    @pytest.mark.parametrize(
        "junk",
        [
            None,
            "",
            "   ",
            "{}",
            "None",
            "NULL",
            "N/A",
            "Unknown",
            "To Be Filled By O.E.M.",
            "Default string",
            "Not Specified",
            "00000000-0000-0000-0000-000000000000",
            "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF",
            "1234567890",
            "abc",
        ],
    )
    def test_placeholder_values_filtered(self, junk):
        assert normalize_anchor_value("smbios_uuid", junk) is None

    def test_valid_anchor_normalization(self):
        assert (
            normalize_anchor_value("machine_guid", " {a1b2c3d4-e5f6-7890} ")
            == "A1B2C3D4E5F67890"
        )

    def test_fewer_than_two_valid_anchors_rejected(self):
        with pytest.raises(FingerprintError):
            build_fingerprint_bytes(
                {
                    "machine_guid": PC_A_ANCHORS["machine_guid"],
                    "smbios_uuid": "To Be Filled By O.E.M.",
                    "disk_serial": "000000000000",
                    "volume_serial": None,
                }
            )

    def test_synthetic_smbios_type1_uuid_parser(self):
        uuid_bytes = bytes.fromhex("00112233445566778899AABBCCDDEEFF")
        # RawSMBIOSData header (8B) + Type 0 (4B struct + "BIOS\0\0") + Type 1 (0x1B struct + "\0\0") + Type 127
        type0 = bytes([0, 4, 0, 0]) + b"BIOS\x00\x00"
        type1 = bytearray([1, 0x1B, 1, 0, 1, 2, 3, 4]) + uuid_bytes + bytes([0x06, 5, 6])
        type1_full = bytes(type1) + b"\x00\x00"
        type127 = bytes([127, 4, 0, 0]) + b"\x00\x00"
        body = type0 + type1_full + type127
        rsmb = struct.pack("<BBBBI", 0, 3, 0, 0, len(body)) + body

        assert parse_smbios_type1_uuid(rsmb) == "00112233445566778899AABBCCDDEEFF"
        assert parse_smbios_type1_uuid(b"short") is None

    def test_synthetic_storage_device_serial_parser(self):
        # 40-byte header with SerialNumberOffset at byte 24 pointing to offset 40
        buf = bytearray(40)
        struct.pack_into("<I", buf, 24, 40)
        buf.extend(b"WD-WCC6Y7AA1234\x00extra")
        assert parse_storage_device_serial(bytes(buf)) == "WD-WCC6Y7AA1234"

        # Offset 0 -> None
        buf_zero = bytearray(40)
        assert parse_storage_device_serial(bytes(buf_zero)) is None
        assert parse_storage_device_serial(b"too_short") is None


# ── 2. Fuzzy Tolerance & Anti-Cloning Matrix ─────────────────────────────────


class TestFingerprintTolerance:
    def test_four_anchor_tolerance_matrix(self):
        fp_target = build_fingerprint_bytes(PC_A_ANCHORS)

        # Exact PC (4/4)
        res = match_fingerprints(fp_target, fp_target)
        assert res.matched is True
        assert res.matched_anchors == (0, 1, 2, 3)

        # SSD swapped (disk_serial changed -> 3/4)
        ssd_swapped = {**PC_A_ANCHORS, "disk_serial": "NEW-NVME-9999"}
        assert match_fingerprints(fp_target, build_fingerprint_bytes(ssd_swapped)).matched is True

        # Windows Update changed MachineGuid (3/4)
        guid_changed = {**PC_A_ANCHORS, "machine_guid": "DEADBEEF-0000-1111-2222-333344445555"}
        assert match_fingerprints(fp_target, build_fingerprint_bytes(guid_changed)).matched is True

        # Clean Windows reinstall on same PC/SSD (OS+Vol changed, SMBIOS+Disk preserved -> 2/4 hw)
        reinstall = {
            **PC_A_ANCHORS,
            "machine_guid": "AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE",
            "volume_serial": "CAFEBABE",
        }
        res_reinstall = match_fingerprints(fp_target, build_fingerprint_bytes(reinstall))
        assert res_reinstall.matched is True
        assert set(res_reinstall.matched_anchors) == {ANCHOR_SMBIOS_UUID, ANCHOR_DISK_SERIAL}

        # Cloned OS disk moved to DIFFERENT motherboard+disk (OS+Vol match, SMBIOS+Disk differ -> FAIL)
        cloned_os = {
            **PC_A_ANCHORS,
            "smbios_uuid": PC_B_ANCHORS["smbios_uuid"],
            "disk_serial": PC_B_ANCHORS["disk_serial"],
        }
        res_clone = match_fingerprints(fp_target, build_fingerprint_bytes(cloned_os))
        assert res_clone.matched is False
        assert set(res_clone.matched_anchors) == {ANCHOR_MACHINE_GUID, ANCHOR_VOLUME_SERIAL}

        # Completely different PC
        assert match_fingerprints(fp_target, build_fingerprint_bytes(PC_B_ANCHORS)).matched is False

    def test_three_and_two_anchor_thresholds(self):
        three = {**PC_A_ANCHORS, "disk_serial": None}
        fp3 = build_fingerprint_bytes(three)

        three_one_changed = {**three, "volume_serial": "DEAD1234"}
        assert match_fingerprints(fp3, build_fingerprint_bytes(three_one_changed)).matched is True

        three_two_changed = {
            **three,
            "volume_serial": "DEAD1234",
            "smbios_uuid": PC_B_ANCHORS["smbios_uuid"],
        }
        assert match_fingerprints(fp3, build_fingerprint_bytes(three_two_changed)).matched is False

        two = {
            "machine_guid": PC_A_ANCHORS["machine_guid"],
            "smbios_uuid": None,
            "disk_serial": None,
            "volume_serial": PC_A_ANCHORS["volume_serial"],
        }
        fp2 = build_fingerprint_bytes(two)
        assert match_fingerprints(fp2, fp2).matched is True

        two_one_changed = {**two, "volume_serial": "CAFEBABE"}
        assert match_fingerprints(fp2, build_fingerprint_bytes(two_one_changed)).matched is False

    def test_missing_zero_digests_never_falsely_match(self):
        # PC1 missing smbios+disk; PC2 also missing smbios+disk, with different guid+vol
        pc1 = {
            "machine_guid": PC_A_ANCHORS["machine_guid"],
            "smbios_uuid": None,
            "disk_serial": None,
            "volume_serial": PC_A_ANCHORS["volume_serial"],
        }
        pc2 = {
            "machine_guid": PC_B_ANCHORS["machine_guid"],
            "smbios_uuid": None,
            "disk_serial": None,
            "volume_serial": PC_B_ANCHORS["volume_serial"],
        }
        res = match_fingerprints(build_fingerprint_bytes(pc1), build_fingerprint_bytes(pc2))
        assert res.matched is False
        assert res.matched_anchors == ()


# ── 3. Ed25519 Codec & Key Management ────────────────────────────────────────


class TestCodec:
    def test_keypair_generation_and_passphrase_protection(self):
        with pytest.raises(ValueError, match="8 characters"):
            generate_keypair("short")

        pem_bytes, pub_b64 = generate_keypair("ValidSecret#99")
        assert b"BEGIN ENCRYPTED PRIVATE KEY" in pem_bytes

        with pytest.raises(Exception):
            load_private_key(pem_bytes, "WrongPassphrase")
        with pytest.raises(ValueError):
            load_private_key(pem_bytes, "")

        priv = load_private_key(pem_bytes, "ValidSecret#99")
        loaded_pub = load_ed25519_public_key(pub_b64)
        assert loaded_pub.public_bytes_raw() == priv.public_key().public_bytes_raw()

    def test_sign_verify_and_whatsapp_extraction(self, keypair):
        _, priv, pub_b64 = keypair
        req_code = get_request_code(PC_A_ANCHORS)
        signed = sign_license_token(
            req_code, priv, issued_on=date(2026, 11, 9), license_id_num=0xABCDEF12
        )

        assert re.fullmatch(r"UIIC1-[A-Za-z0-9_-]{112}", signed.token)
        assert len(signed.token) == 118
        assert signed.license_id == "LIC-ABCDEF12"
        assert signed.request_code == req_code

        # Direct verification
        verified = parse_and_verify_token(signed.token, public_key_b64=pub_b64)
        assert verified.license_id == "LIC-ABCDEF12"
        assert verified.issued_date == "2026-11-09"
        assert verified.flags == 0

        # WhatsApp line wrapping + surrounding greeting text
        wrapped = (
            "Hello friend! Here is your key:\n\n"
            + signed.token[:35]
            + "\n"
            + signed.token[35:75]
            + "\r\n"
            + signed.token[75:]
            + "\n\nPaste and activate!"
        )
        assert extract_token_string(wrapped) == signed.token
        assert parse_and_verify_token(wrapped, public_key_b64=pub_b64).license_id == "LIC-ABCDEF12"

        # .lic JSON format round-trip
        lic_json = format_lic_file_content(signed)
        assert parse_and_verify_token(lic_json, public_key_b64=pub_b64).token == signed.token

    def test_tampering_wrong_key_and_flag_rejections(self, keypair):
        import base64

        _, priv, pub_b64 = keypair
        req_code = get_request_code(PC_A_ANCHORS)
        signed = sign_license_token(req_code, priv)

        # Flip 1 character in payload region
        chars = list(signed.token)
        idx = len(TOKEN_PREFIX) + 4
        chars[idx] = "B" if chars[idx] != "B" else "C"
        with pytest.raises(Exception, match="signature|tampered|corrupted|invalid"):
            parse_and_verify_token("".join(chars), public_key_b64=pub_b64)

        # Flip 1 character near end (signature region)
        sig_chars = list(signed.token)
        sig_chars[-2] = "Z" if sig_chars[-2] != "Z" else "Y"
        with pytest.raises(Exception):
            parse_and_verify_token("".join(sig_chars), public_key_b64=pub_b64)

        # Wrong public key
        _, other_pub_b64 = generate_keypair("OtherPassphrase123")
        with pytest.raises(Exception):
            parse_and_verify_token(signed.token, public_key_b64=other_pub_b64)

        # Unconfigured key
        with pytest.raises(PublicKeyNotConfiguredError):
            parse_and_verify_token(signed.token, public_key_b64="UNCONFIGURED")

        # Signed token with unsupported flags != 0
        decoded = decode_request_code(req_code)
        bad_payload = PAYLOAD_STRUCT.pack(PAYLOAD_MAGIC, decoded.raw_bytes, 123, 10, 1)
        bad_sig = priv.sign(bad_payload)
        bad_tok = TOKEN_PREFIX + base64.urlsafe_b64encode(bad_payload + bad_sig).decode("ascii").rstrip("=")
        with pytest.raises(Exception, match="flags"):
            parse_and_verify_token(bad_tok, public_key_b64=pub_b64)

        # Signed token with wrong magic
        bad_magic_payload = PAYLOAD_STRUCT.pack(b"U2", decoded.raw_bytes, 123, 10, 0)
        bad_magic_sig = priv.sign(bad_magic_payload)
        bad_magic_tok = (
            TOKEN_PREFIX
            + base64.urlsafe_b64encode(bad_magic_payload + bad_magic_sig).decode("ascii").rstrip("=")
        )
        with pytest.raises(Exception, match="Unsupported license payload format"):
            parse_and_verify_token(bad_magic_tok, public_key_b64=pub_b64)


# ── 4. Verifier, Persistence & Security Rules ────────────────────────────────


class TestVerifierAndSecurity:
    def test_activate_and_verify_lifecycle(self, tmp_path, keypair):
        _, priv, pub_b64 = keypair
        lic_path = tmp_path / "appdata" / "license.lic"
        fp_a = build_fingerprint_bytes(PC_A_ANCHORS)
        fp_b = build_fingerprint_bytes(PC_B_ANCHORS)

        assert verify_stored_license(license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a).reason == "missing"

        # Issue for PC A
        signed_a = sign_license_token(get_request_code(PC_A_ANCHORS), priv)

        # Mismatched PC activation fails and MUST NOT write license.lic
        bad_status = activate_license(
            signed_a.token, license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_b
        )
        assert bad_status.valid is False
        assert bad_status.reason == "hardware_mismatch"
        assert not lic_path.exists()

        # Matching PC activation succeeds and writes atomically
        ok_status = activate_license(
            signed_a.token, license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a
        )
        assert ok_status.valid is True
        assert ok_status.reason == "ok"
        assert lic_path.is_file()
        assert not lic_path.with_suffix(".lic.tmp").exists()

        # Copied license.lic onto PC B fails
        copied_check = verify_stored_license(
            license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_b
        )
        assert copied_check.valid is False
        assert copied_check.reason == "hardware_mismatch"

        # Subsequent invalid activation does NOT clobber existing valid license.lic
        signed_b = sign_license_token(get_request_code(PC_B_ANCHORS), priv)
        assert (
            activate_license(
                signed_b.token, license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a
            ).valid
            is False
        )
        assert (
            verify_stored_license(
                license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a
            ).valid
            is True
        )

    def test_activate_from_file_and_corrupt_file(self, tmp_path, keypair):
        _, priv, pub_b64 = keypair
        fp_a = build_fingerprint_bytes(PC_A_ANCHORS)
        lic_dest = tmp_path / "dest" / "license.lic"

        assert activate_from_file(
            tmp_path / "nonexistent.lic", license_path=lic_dest, public_key_b64=pub_b64, current_fp=fp_a
        ).reason == "file_not_found"

        src_file = tmp_path / "friend.lic"
        signed = sign_license_token(get_request_code(PC_A_ANCHORS), priv)
        src_file.write_text(format_lic_file_content(signed), encoding="utf-8")

        res = activate_from_file(
            src_file, license_path=lic_dest, public_key_b64=pub_b64, current_fp=fp_a
        )
        assert res.valid is True
        assert lic_dest.is_file()

        # Corrupt stored file fails cleanly
        lic_dest.write_text("{broken json", encoding="utf-8")
        corrupt = verify_stored_license(
            license_path=lic_dest, public_key_b64=pub_b64, current_fp=fp_a
        )
        assert corrupt.valid is False
        assert corrupt.reason == "invalid_token"

    def test_frozen_never_bypasses_and_require_valid_license_enforces(
        self, tmp_path, monkeypatch, keypair
    ):
        _, priv, pub_b64 = keypair
        lic_path = tmp_path / "license.lic"
        fp_a = build_fingerprint_bytes(PC_A_ANCHORS)

        # In pytest source run, bypass is active unless forced
        assert is_test_bypass_active() is True
        assert require_valid_license(license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a).reason == "pytest_bypass"

        # With force=True, missing license raises LicenseRequiredError
        with pytest.raises(LicenseRequiredError):
            require_valid_license(force=True, license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a)

        # CRITICAL: Frozen EXE must NEVER bypass even with pytest loaded & PYTEST_CURRENT_TEST set
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setenv("PYTEST_CURRENT_TEST", "spoofed_test")
        assert is_test_bypass_active() is False
        with pytest.raises(LicenseRequiredError):
            require_valid_license(license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a)

        # When activated, frozen mode passes
        signed = sign_license_token(get_request_code(PC_A_ANCHORS), priv)
        activate_license(signed.token, license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a)
        assert require_valid_license(license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a).valid is True

    def test_env_var_alone_in_normal_python_cannot_bypass(self, tmp_path):
        env = os.environ.copy()
        env["PYTEST_CURRENT_TEST"] = "spoofed_bypass_attempt"
        env["LOCALAPPDATA"] = str(tmp_path)
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import sys\n"
                    "from app.licensing.verifier import is_test_bypass_active, require_valid_license, LicenseRequiredError\n"
                    "assert 'pytest' not in sys.modules\n"
                    "assert is_test_bypass_active() is False\n"
                    "try:\n"
                    "    require_valid_license()\n"
                    "    sys.exit(99)\n"
                    "except LicenseRequiredError:\n"
                    "    print('BLOCKED_OK')\n"
                ),
            ],
            cwd=str(REPO_ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert proc.returncode == 0, proc.stderr
        assert "BLOCKED_OK" in proc.stdout

    def test_update_public_key_file_atomic(self, tmp_path, keypair):
        _, _, pub_b64 = keypair
        target = tmp_path / "public_key.py"
        shutil.copy2(REPO_ROOT / "app" / "licensing" / "public_key.py", target)

        update_public_key_file(pub_b64, target_path=target)
        updated_text = target.read_text(encoding="utf-8")
        assert f'PUBLIC_KEY_B64 = "{pub_b64}"' in updated_text
        assert not target.with_suffix(".py.tmp").exists()


# ── 5. PyQt6 ActivationDialog & Startup Gate ─────────────────────────────────


class TestActivationDialogUI:
    def test_activation_dialog_copy_reject_bad_then_accept_good_key(
        self, qapp, tmp_path, keypair
    ):
        from PyQt6.QtWidgets import QApplication, QDialog
        from app.licensing.ui import ActivationDialog

        _, priv, pub_b64 = keypair
        fp_a = build_fingerprint_bytes(PC_A_ANCHORS)
        code_a = get_request_code(PC_A_ANCHORS)
        lic_path = tmp_path / "license.lic"

        initial = verify_stored_license(license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a)
        dlg = ActivationDialog(
            initial,
            license_path=lic_path,
            public_key_b64=pub_b64,
            current_fp=fp_a,
            request_code_override=code_a,
        )
        assert dlg.lbl_code.text() == code_a
        assert dlg.btn_activate.isEnabled()

        dlg._on_copy_code()
        assert QApplication.clipboard().text() == code_a

        # Bad key keeps dialog open and does not write license.lic
        dlg.txt_key.setPlainText("UIIC1-not-a-valid-key")
        dlg._on_activate_clicked()
        assert dlg.result() != QDialog.DialogCode.Accepted
        assert not lic_path.exists()

        # Valid key accepts dialog and saves license.lic
        signed = sign_license_token(code_a, priv)
        dlg.txt_key.setPlainText(signed.token)
        dlg._on_activate_clicked()
        assert dlg.result() == QDialog.DialogCode.Accepted
        assert dlg.activated_status is not None
        assert dlg.activated_status.valid is True
        assert lic_path.is_file()

    def test_activation_dialog_load_lic_file(self, qapp, tmp_path, monkeypatch, keypair):
        from PyQt6.QtWidgets import QDialog, QFileDialog
        from app.licensing.ui import ActivationDialog

        _, priv, pub_b64 = keypair
        fp_a = build_fingerprint_bytes(PC_A_ANCHORS)
        code_a = get_request_code(PC_A_ANCHORS)
        lic_dest = tmp_path / "stored" / "license.lic"

        sent_file = tmp_path / "friend_sent.lic"
        signed = sign_license_token(code_a, priv)
        sent_file.write_text(format_lic_file_content(signed), encoding="utf-8")

        initial = verify_stored_license(license_path=lic_dest, public_key_b64=pub_b64, current_fp=fp_a)
        dlg = ActivationDialog(
            initial,
            license_path=lic_dest,
            public_key_b64=pub_b64,
            current_fp=fp_a,
            request_code_override=code_a,
        )
        monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **kw: (str(sent_file), ""))
        dlg._on_load_file()
        assert dlg.result() == QDialog.DialogCode.Accepted
        assert lic_dest.is_file()

    def test_activation_dialog_unconfigured_key_disables_cleanly(self, qapp, tmp_path):
        from app.licensing.ui import ActivationDialog

        dlg = ActivationDialog(
            LicenseStatus(valid=False, reason="unconfigured", message="Not configured"),
            license_path=tmp_path / "license.lic",
            public_key_b64="UNCONFIGURED",
            current_fp=build_fingerprint_bytes(PC_A_ANCHORS),
            request_code_override=get_request_code(PC_A_ANCHORS),
        )
        assert dlg.btn_activate.isEnabled() is False
        assert dlg.btn_load_file.isEnabled() is False
        assert "Developer setup needed" in dlg.lbl_status.text()

    def test_ensure_activated_or_exit_flows(self, qapp, tmp_path, monkeypatch, keypair):
        from PyQt6.QtWidgets import QDialog
        from app.licensing.ui import ActivationDialog, ensure_activated_or_exit

        _, priv, pub_b64 = keypair
        fp_a = build_fingerprint_bytes(PC_A_ANCHORS)
        lic_path = tmp_path / "license.lic"

        # Cancel on prompt -> clean SystemExit(0)
        monkeypatch.setattr(ActivationDialog, "exec", lambda self: int(QDialog.DialogCode.Rejected))
        with pytest.raises(SystemExit) as exit_exc:
            ensure_activated_or_exit(
                qapp,
                force=True,
                license_path=lic_path,
                public_key_b64=pub_b64,
                current_fp=fp_a,
            )
        assert exit_exc.value.code == 0

        # Already licensed -> skips dialog cleanly
        signed = sign_license_token(get_request_code(PC_A_ANCHORS), priv)
        activate_license(signed.token, license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a)
        monkeypatch.setattr(
            ActivationDialog,
            "exec",
            lambda self: pytest.fail("ActivationDialog must not open when already licensed"),
        )
        st = ensure_activated_or_exit(
            qapp,
            force=True,
            license_path=lic_path,
            public_key_b64=pub_b64,
            current_fp=fp_a,
        )
        assert st.valid is True


# ── 6. Standalone Developer License Generator ────────────────────────────────


class TestLicenseGenerator:
    def test_issuer_store_lifecycle(self, tmp_path):
        from tools.license_generator import IssuerStore

        data_dir = tmp_path / "issuer_vault"
        pub_copy = tmp_path / "public_key.py"
        shutil.copy2(REPO_ROOT / "app" / "licensing" / "public_key.py", pub_copy)
        store = IssuerStore(data_dir=data_dir, public_key_file=pub_copy)

        assert store.has_private_key() is False
        with pytest.raises(ValueError, match="do not match"):
            store.initialize_keypair("MySecret123", "Different123")

        priv, pub_b64 = store.initialize_keypair("MySecret123", "MySecret123", sync_public_key=True)
        assert store.has_private_key() is True
        state, derived, embedded = store.public_key_sync_status(priv)
        assert state == "synced"
        assert derived == embedded == pub_b64

        # Cannot overwrite existing key
        with pytest.raises(FileExistsError):
            store.initialize_keypair("AnotherPass1", "AnotherPass1")

        # Wrong vs right unlock passphrase
        with pytest.raises(ValueError):
            store.unlock_private_key("WrongPass")
        unlocked = store.unlock_private_key("MySecret123")
        assert unlocked.public_key().public_bytes_raw() == priv.public_key().public_bytes_raw()

        # Issue licenses for friends and verify offline
        code_a = get_request_code(PC_A_ANCHORS)
        signed = store.issue_license(unlocked, "Friend 1 - Rajesh", code_a)
        st = verify_license_token(
            signed.token,
            public_key_b64=pub_b64,
            current_fp=build_fingerprint_bytes(PC_A_ANCHORS),
        )
        assert st.valid is True
        assert st.license_id == signed.license_id

        history = store.load_history()
        assert len(history) == 1
        assert history[0]["friend_name"] == "Friend 1 - Rajesh"

        # Backup keeps encryption intact
        backup = store.export_backup_pem(tmp_path / "backup.pem")
        assert b"ENCRYPTED PRIVATE KEY" in backup.read_bytes()

    def test_generator_cli_end_to_end(self, tmp_path):
        from tools.license_generator import IssuerStore, run_cli

        data_dir = tmp_path / "cli_vault"
        pub_copy = tmp_path / "public_key.py"
        shutil.copy2(REPO_ROOT / "app" / "licensing" / "public_key.py", pub_copy)
        store = IssuerStore(data_dir=data_dir, public_key_file=pub_copy)

        exported_lic = tmp_path / "friend_cli.lic"
        backup_pem = tmp_path / "backup_cli.pem"
        exported_uikey = tmp_path / "OwnerKey.uikey"
        code_a = get_request_code(PC_A_ANCHORS)

        # First-time setup (rejects short & mismatch) + issue + export .uikey + backup + exit
        secrets_1 = iter(
            [
                "short",
                "Mismatch1",
                "Mismatch2",
                "CliPass#2026",
                "CliPass#2026",
                "12",        # reject <4 char Setup Code on Option 5 attempt 1
                "8842",      # reject mismatched confirm on Option 5 attempt 2
                "9999",
                "447711",    # valid Setup Code + confirm on Option 5 attempt 3
                "447711",
            ]
        )
        inputs_1 = iter(
            [
                "Y",  # sync public key
                "1",  # issue license
                "Friend CLI",
                code_a,
                str(exported_lic),
                "3",  # view history
                "4",  # backup key
                str(backup_pem),
                "5",  # attempt 1 (short Setup Code -> returns to menu)
                str(exported_uikey),
                "5",  # attempt 2 (mismatch Setup Code -> returns to menu)
                str(exported_uikey),
                "5",  # attempt 3 (succeeds)
                str(exported_uikey),
                "0",  # exit
            ]
        )
        out_1: list[str] = []
        rc1 = run_cli(
            store,
            input_fn=lambda _p="": next(inputs_1),
            secret_fn=lambda _p="": next(secrets_1),
            output_fn=out_1.append,
        )
        assert rc1 == 0
        assert store.has_private_key()
        assert exported_lic.is_file()
        assert backup_pem.is_file()
        assert exported_uikey.is_file()
        assert any("Friend CLI" in line for line in out_1)

        from tools.owner_vault import decrypt_owner_bundle

        embedded_pub = store.read_embedded_public_key_b64()
        uikey_priv, uikey_pub = decrypt_owner_bundle(
            exported_uikey, "447711", expected_public_key_b64=embedded_pub
        )
        assert uikey_pub == embedded_pub
        assert uikey_priv is not None
        dest_lic = tmp_path / "pc_a.lic"
        act = activate_from_file(
            exported_lic,
            license_path=dest_lic,
            public_key_b64=embedded_pub,
            current_fp=build_fingerprint_bytes(PC_A_ANCHORS),
        )
        assert act.valid is True

        # Re-open CLI with wrong then right passphrase
        secrets_2 = iter(["WrongPass", "CliPass#2026"])
        inputs_2 = iter(["0"])
        out_2: list[str] = []
        rc2 = run_cli(
            IssuerStore(data_dir=data_dir, public_key_file=pub_copy),
            input_fn=lambda _p="": next(inputs_2),
            secret_fn=lambda _p="": next(secrets_2),
            output_fn=out_2.append,
        )
        assert rc2 == 0
        assert any("SYNCED" in line for line in out_2)

    def test_generator_gui_setup_unlock_issue_and_export(self, qapp, tmp_path, monkeypatch):
        from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
        from tools.license_generator import IssuerStore, get_generator_window_class

        LicenseGeneratorWindow = get_generator_window_class()

        data_dir = tmp_path / "vault"
        pub_copy = tmp_path / "public_key.py"
        shutil.copy2(REPO_ROOT / "app" / "licensing" / "public_key.py", pub_copy)
        store = IssuerStore(data_dir=data_dir, public_key_file=pub_copy)

        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: QMessageBox.StandardButton.Ok)

        win = LicenseGeneratorWindow(store)
        assert win.stack.currentWidget() is win.page_setup

        # Setup passphrase mismatch shows error banner
        win.txt_setup_pass.setText("MasterPass#1")
        win.txt_setup_confirm.setText("Mismatch#1")
        win._on_create_keypair()
        assert win.stack.currentWidget() is win.page_setup
        assert not win.lbl_setup_err.isHidden()
        assert "do not match" in win.lbl_setup_err.text()

        # Valid setup enters main page and syncs public key
        win.txt_setup_confirm.setText("MasterPass#1")
        win._on_create_keypair()
        assert win.stack.currentWidget() is win.page_main
        assert "SYNCED" in win.lbl_sync_status.text()

        # Issue key for friend PC_B
        code_b = get_request_code(PC_B_ANCHORS)
        win.txt_friend_name.setText("Friend 2 - Amit")
        win.txt_request_code.setText(code_b.lower().replace("-", " "))
        assert "Valid code (4/4" in win.lbl_code_check.text()

        win._on_generate_license()
        issued_token = win.txt_output_token.toPlainText()
        assert issued_token.startswith(TOKEN_PREFIX)
        assert win.tbl_history.rowCount() == 1

        # Copy token & WhatsApp message
        win._on_copy_token()
        assert QApplication.clipboard().text() == issued_token
        win._on_copy_whatsapp()
        assert issued_token in QApplication.clipboard().text()

        # Export .lic and verify it activates on friend PC_B
        exported_lic = tmp_path / "friend2.lic"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(exported_lic), ""))
        win._on_save_lic()
        assert exported_lic.is_file()

        embedded_pub = store.read_embedded_public_key_b64()
        dest_pc_b = tmp_path / "pc_b_license.lic"
        act = activate_from_file(
            exported_lic,
            license_path=dest_pc_b,
            public_key_b64=embedded_pub,
            current_fp=build_fingerprint_bytes(PC_B_ANCHORS),
        )
        assert act.valid is True

        # Re-open generator: starts on Unlock page, rejects wrong password, unlocks on correct password
        win2 = LicenseGeneratorWindow(IssuerStore(data_dir=data_dir, public_key_file=pub_copy))
        assert win2.stack.currentWidget() is win2.page_unlock
        win2.txt_unlock_pass.setText("WrongPassword")
        win2._on_unlock()
        assert win2.stack.currentWidget() is win2.page_unlock
        win2.txt_unlock_pass.setText("MasterPass#1")
        win2._on_unlock()
        assert win2.stack.currentWidget() is win2.page_main
        assert win2.tbl_history.rowCount() == 1


# ── 7. Owner Vault (.uikey, Windows DPAPI auto-unlock & PIN) & Owner GUI ────


class TestOwnerVault:
    def test_uikey_bundle_export_decrypt_and_rejections(self, tmp_path, keypair):
        from tools.owner_vault import (
            UIKEY_FORMAT,
            decrypt_owner_bundle,
            export_owner_bundle,
        )

        _, priv, pub_b64 = keypair
        uikey_path = tmp_path / "OwnerKey.uikey"

        with pytest.raises(ValueError, match="at least 4"):
            export_owner_bundle(priv, "12", uikey_path)

        export_owner_bundle(priv, "8842", uikey_path)
        assert uikey_path.is_file()
        assert not uikey_path.with_suffix(".uikey.tmp").exists()

        # Right setup code + matching expected_public_key_b64 succeeds
        loaded_priv, loaded_pub = decrypt_owner_bundle(
            uikey_path, "8842", expected_public_key_b64=pub_b64
        )
        assert loaded_pub == pub_b64
        assert loaded_priv.public_key().public_bytes_raw() == priv.public_key().public_bytes_raw()

        # Missing file / blank / wrong Setup Code
        with pytest.raises(FileNotFoundError):
            decrypt_owner_bundle(tmp_path / "missing.uikey", "8842")
        with pytest.raises(ValueError, match="Setup Code"):
            decrypt_owner_bundle(uikey_path, "  ")
        with pytest.raises(ValueError, match="Wrong Setup Code"):
            decrypt_owner_bundle(uikey_path, "9999", expected_public_key_b64=pub_b64)

        # Mismatched expected app public key
        _, other_pub = generate_keypair("AnotherStrongKey#99")
        with pytest.raises(ValueError, match="does not match"):
            decrypt_owner_bundle(uikey_path, "8842", expected_public_key_b64=other_pub)

        # Consistency check if public_key_b64 field is swapped
        obj = json.loads(uikey_path.read_text(encoding="utf-8"))
        tampered_pub = tmp_path / "tampered_pub.uikey"
        obj_bad_pub = {**obj, "public_key_b64": other_pub}
        tampered_pub.write_text(json.dumps(obj_bad_pub), encoding="utf-8")
        with pytest.raises(ValueError, match="consistency"):
            decrypt_owner_bundle(tampered_pub, "8842", expected_public_key_b64="")

        # Tampered ciphertext fails AES-GCM tag
        import base64

        raw_ct = bytearray(base64.b64decode(obj["ciphertext_b64"]))
        raw_ct[0] ^= 0xFF
        obj_bad_ct = {**obj, "ciphertext_b64": base64.b64encode(bytes(raw_ct)).decode("ascii")}
        tampered_ct = tmp_path / "tampered_ct.uikey"
        tampered_ct.write_text(json.dumps(obj_bad_ct), encoding="utf-8")
        with pytest.raises(ValueError, match="Wrong Setup Code"):
            decrypt_owner_bundle(tampered_ct, "8842", expected_public_key_b64=pub_b64)

        # Unsupported format / corrupt JSON
        bad_fmt = tmp_path / "bad_fmt.uikey"
        bad_fmt.write_text(json.dumps({"format": f"{UIKEY_FORMAT}-x"}), encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported"):
            decrypt_owner_bundle(bad_fmt, "8842")

        corrupt = tmp_path / "corrupt.uikey"
        corrupt.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError, match="not a valid"):
            decrypt_owner_bundle(corrupt, "8842")

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows DPAPI test")
    def test_owner_vault_dpapi_and_pin_lifecycle(self, tmp_path, keypair):
        from tools.owner_vault import OwnerVault, export_owner_bundle

        _, priv, pub_b64 = keypair
        uikey_path = tmp_path / "OwnerKey.uikey"
        export_owner_bundle(priv, "setup-77", uikey_path)

        # 1. Windows DPAPI auto-unlock flow
        vault = OwnerVault(data_dir=tmp_path / "owner_data", expected_public_key_b64=pub_b64)
        assert vault.has_vault() is False
        assert vault.auto_unlock() is None

        imported = vault.import_uikey_and_save(uikey_path, "setup-77", unlock_mode="dpapi")
        assert vault.has_vault() is True
        assert vault.unlock_mode() == "dpapi"
        assert imported.public_key().public_bytes_raw() == priv.public_key().public_bytes_raw()

        vault_json_text = vault.vault_path.read_text(encoding="utf-8")
        assert "dpapi_b64" in vault_json_text
        assert "BEGIN PRIVATE KEY" not in vault_json_text
        assert "setup-77" not in vault_json_text

        auto_priv = vault.auto_unlock()
        assert auto_priv is not None
        assert auto_priv.public_key().public_bytes_raw() == priv.public_key().public_bytes_raw()

        # Issue and verify offline for PC_A, ensure PC_B fails
        with pytest.raises(ValueError, match="name"):
            vault.issue_license(auto_priv, "   ", get_request_code(PC_A_ANCHORS))
        signed = vault.issue_license(auto_priv, "Rajesh Office", get_request_code(PC_A_ANCHORS))
        assert (
            verify_license_token(
                signed.token,
                public_key_b64=pub_b64,
                current_fp=build_fingerprint_bytes(PC_A_ANCHORS),
            ).valid
            is True
        )
        assert (
            verify_license_token(
                signed.token,
                public_key_b64=pub_b64,
                current_fp=build_fingerprint_bytes(PC_B_ANCHORS),
            ).valid
            is False
        )
        history = vault.load_history()
        assert len(history) == 1
        assert history[0]["friend_name"] == "Rajesh Office"

        # Switching DPAPI -> PIN and back
        with pytest.raises(ValueError, match="do not match"):
            vault.change_unlock_mode(auto_priv, "pin", pin="1234", confirm_pin="9999")
        vault.change_unlock_mode(auto_priv, "pin", pin="2468", confirm_pin="2468")
        assert vault.unlock_mode() == "pin"
        assert vault.auto_unlock() is None
        with pytest.raises(ValueError, match="Wrong PIN"):
            vault.unlock_with_pin("0000")
        pin_priv = vault.unlock_with_pin("2468")
        assert pin_priv.public_key().public_bytes_raw() == priv.public_key().public_bytes_raw()

        # Switching PIN -> DPAPI
        vault.change_unlock_mode(pin_priv, "dpapi")
        assert vault.unlock_mode() == "dpapi"
        assert vault.auto_unlock() is not None

        # Tampered DPAPI payload fails gracefully rather than crashing
        v_obj = json.loads(vault.vault_path.read_text(encoding="utf-8"))
        v_obj["dpapi_b64"] = "AAAA"
        vault.vault_path.write_text(json.dumps(v_obj), encoding="utf-8")
        with pytest.raises(ValueError, match="Could not unlock automatically"):
            vault.auto_unlock()

        # Reset removes vault JSON but leaves history intact
        vault.reset_vault()
        assert vault.has_vault() is False
        assert len(vault.load_history()) == 1

    def test_find_nearby_uikey_discovery_and_pin_setup_validation(self, tmp_path, keypair):
        from tools.owner_vault import OwnerVault, export_owner_bundle

        _, priv, pub_b64 = keypair
        d_empty = tmp_path / "empty"
        d_empty.mkdir()
        assert OwnerVault.find_nearby_uikey([d_empty]) is None

        # Single custom-named .uikey is found
        d_single = tmp_path / "single"
        custom_key = d_single / "RajeshSetup.uikey"
        export_owner_bundle(priv, "4321", custom_key)
        assert OwnerVault.find_nearby_uikey([d_single]) == custom_key

        # Multiple files with OwnerKey.uikey prefers OwnerKey.uikey
        preferred = d_single / "OwnerKey.uikey"
        export_owner_bundle(priv, "4321", preferred)
        assert OwnerVault.find_nearby_uikey([d_single]) == preferred

        # Ambiguous multiple files without OwnerKey.uikey returns None
        preferred.unlink()
        export_owner_bundle(priv, "4321", d_single / "Second.uikey")
        assert OwnerVault.find_nearby_uikey([d_single]) is None

        # PIN import validations (short / mismatch / wrong unlock call in dpapi vs pin)
        vault = OwnerVault(data_dir=tmp_path / "pin_only", expected_public_key_b64=pub_b64)
        with pytest.raises(ValueError, match="at least 4"):
            vault.import_uikey_and_save(
                custom_key, "4321", unlock_mode="pin", pin="12", confirm_pin="12"
            )
        with pytest.raises(ValueError, match="do not match"):
            vault.import_uikey_and_save(
                custom_key, "4321", unlock_mode="pin", pin="1234", confirm_pin="5678"
            )
        vault.import_uikey_and_save(
            custom_key, "4321", unlock_mode="pin", pin="5566", confirm_pin="5566"
        )
        assert vault.auto_unlock() is None
        with pytest.raises(ValueError, match="enter your PIN"):
            vault.unlock_with_pin(" ")
        unlocked = vault.unlock_with_pin("5566")
        assert unlocked.public_key().public_bytes_raw() == priv.public_key().public_bytes_raw()


class TestOwnerGeneratorUI:
    def test_owner_ui_has_zero_developer_jargon(self):
        # Owner UI source must stay plain-English (never expose dev terms to the owner)
        src = (REPO_ROOT / "tools" / "owner_generator_app.py").read_text(encoding="utf-8")
        # Strip module docstring before scanning so internal header comment doesn't trip check
        body = src.split('"""', 2)[-1]
        for forbidden in ("Master Passphrase", "public_key.py", "Git", "Ed25519", "anchors", "--dev"):
            # Allow "--dev" ONLY inside stderr CLI fallback message in main()
            if forbidden == "--dev":
                ui_part = body.split("def main(")[0]
                assert forbidden not in ui_part
            elif forbidden == "Ed25519":
                # Type annotation Ed25519PrivateKey uses identifier, check plain prose only
                assert "Ed25519 " not in body
            else:
                assert forbidden not in body, f"Developer jargon leaked into Owner UI: {forbidden}"

    def test_owner_gui_setup_dpapi_issue_and_pin_flow(self, qapp, tmp_path, monkeypatch, keypair):
        from PyQt6.QtWidgets import QApplication, QFileDialog, QMessageBox
        from tools.owner_generator_app import get_owner_window_class
        from tools.owner_vault import OwnerVault, export_owner_bundle

        OwnerGeneratorWindow = get_owner_window_class()
        _, priv, pub_b64 = keypair
        uikey_path = tmp_path / "OwnerKey.uikey"
        export_owner_bundle(priv, "9012", uikey_path)

        monkeypatch.setattr(QMessageBox, "information", lambda *a, **kw: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "warning", lambda *a, **kw: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(QMessageBox, "critical", lambda *a, **kw: QMessageBox.StandardButton.Ok)
        monkeypatch.setattr(OwnerVault, "find_nearby_uikey", staticmethod(lambda dirs=None: uikey_path))

        data_dir = tmp_path / "owner_ui_data"
        vault = OwnerVault(data_dir=data_dir, expected_public_key_b64=pub_b64)
        win = OwnerGeneratorWindow(vault)
        assert win.stack.currentWidget() is win.page_setup
        assert win.txt_uikey_path.text() == str(uikey_path)
        assert "Found setup file" in win.lbl_setup_info.text()

        # Wrong Setup Code keeps window on Setup page with clear error
        win.txt_setup_code.setText("wrong")
        win._on_complete_setup()
        assert win.stack.currentWidget() is win.page_setup
        assert not win.lbl_setup_err.isHidden()
        assert "Wrong Setup Code" in win.lbl_setup_err.text()

        # Correct Setup Code completes setup (auto-unlock DPAPI on Windows, PIN elsewhere)
        win.txt_setup_code.setText("9012")
        if not win.rb_setup_auto.isEnabled():
            win.txt_setup_pin.setText("4455")
            win.txt_setup_pin_confirm.setText("4455")
        win._on_complete_setup()
        assert win.stack.currentWidget() is win.page_main
        assert win.txt_setup_code.text() == ""

        # Issue key for PC_A + copy WhatsApp + export .lic + activate offline
        code_a = get_request_code(PC_A_ANCHORS)
        win.txt_friend_name.setText("Friend 1")
        win.txt_request_code.setText(code_a.lower())
        assert "Code looks good" in win.lbl_code_check.text()
        win._on_generate_license()
        tok = win.txt_output_token.toPlainText()
        assert tok.startswith(TOKEN_PREFIX)
        assert win.tbl_history.rowCount() == 1

        win._on_copy_whatsapp()
        wa_text = QApplication.clipboard().text()
        assert "Friend 1" in wa_text and tok in wa_text

        win._on_copy_token()
        assert QApplication.clipboard().text() == tok

        saved_lic = tmp_path / "Friend_1_License.lic"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *a, **kw: (str(saved_lic), ""))
        win._on_save_lic()
        assert saved_lic.is_file()
        act = activate_from_file(
            saved_lic,
            license_path=tmp_path / "installed.lic",
            public_key_b64=pub_b64,
            current_fp=build_fingerprint_bytes(PC_A_ANCHORS),
        )
        assert act.valid is True

        # Switch vault to PIN mode and verify relaunch lands on PIN screen
        win.vault.change_unlock_mode(priv, "pin", pin="7890", confirm_pin="7890")
        win2 = OwnerGeneratorWindow(OwnerVault(data_dir=data_dir, expected_public_key_b64=pub_b64))
        assert win2.stack.currentWidget() is win2.page_pin
        win2.txt_unlock_pin.setText("0000")
        win2._on_unlock_pin()
        assert win2.stack.currentWidget() is win2.page_pin
        assert not win2.lbl_pin_err.isHidden()
        assert "Wrong PIN" in win2.lbl_pin_err.text()
        win2.txt_unlock_pin.setText("7890")
        win2._on_unlock_pin()
        assert win2.stack.currentWidget() is win2.page_main
        assert win2.tbl_history.rowCount() == 1


# ── 8. Runtime Integration & Packaging Hygiene ───────────────────────────────


class TestRuntimeIntegration:
    def test_headless_subprocess_blocked_without_license(self, tmp_path):
        env = os.environ.copy()
        env["LOCALAPPDATA"] = str(tmp_path)
        for flag, extra in (
            ("--headless-pdf-render", ["dummy.xlsx", "dummy.pdf"]),
            ("--headless-reinspection-render", ["dummy.xlsx", "dummy.pdf", "2"]),
        ):
            proc = subprocess.run(
                [sys.executable, "main.py", flag, *extra],
                cwd=str(REPO_ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=20,
            )
            assert proc.returncode == 1
            assert "License" in (proc.stderr + proc.stdout)

    def test_automation_engine_enforces_license_gate(self, tmp_path, monkeypatch, keypair):
        import app.licensing.verifier as verifier_mod

        _, priv, pub_b64 = keypair
        lic_path = tmp_path / "license.lic"
        fp_a = build_fingerprint_bytes(PC_A_ANCHORS)

        monkeypatch.setattr(verifier_mod, "is_test_bypass_active", lambda: False)
        monkeypatch.setattr(verifier_mod, "default_license_path", lambda: lic_path)
        monkeypatch.setattr(
            verifier_mod,
            "build_fingerprint_bytes",
            lambda anchors=None: fp_a,
        )
        monkeypatch.setattr("app.licensing.public_key.PUBLIC_KEY_B64", pub_b64)

        logs = []
        engine = AutomationEngine("uiic", log_cb=logs.append)
        res_fail = asyncio.run(engine.run_automation(ClaimData()))
        assert res_fail.success is False
        assert "License check failed" in res_fail.message

        # Now activate and request stop cleanly -> license gate passes, hits stop check instead
        signed = sign_license_token(get_request_code(PC_A_ANCHORS), priv)
        activate_license(signed.token, license_path=lic_path, public_key_b64=pub_b64, current_fp=fp_a)
        engine2 = AutomationEngine("uiic", log_cb=logs.append)
        engine2.request_stop()
        res_pass = asyncio.run(engine2.run_automation(ClaimData()))
        assert res_pass.success is False
        assert "stopped by user" in res_pass.message.lower()

    def test_packaging_hygiene_no_private_keys_or_tools_in_app(self):
        # 1. Never import tools/ inside app/ or main.py
        import_re = re.compile(r"^\s*(?:from|import)\s+tools\b", re.MULTILINE)
        for py_file in list((REPO_ROOT / "app").rglob("*.py")) + [REPO_ROOT / "main.py"]:
            txt = py_file.read_text(encoding="utf-8")
            assert not import_re.search(txt), f"Production code imports tools/: {py_file}"
            assert "BEGIN ENCRYPTED PRIVATE KEY" not in txt
            assert "BEGIN PRIVATE KEY" not in txt

        # 2. PUBLIC_KEY_B64 is either UNCONFIGURED or a valid 32-byte Ed25519 key
        if PUBLIC_KEY_B64 != "UNCONFIGURED":
            assert is_public_key_configured(PUBLIC_KEY_B64)
            load_ed25519_public_key(PUBLIC_KEY_B64)

        # 3. All licensing, entry point, and generator source files compile cleanly
        import ast

        for path in [
            *(REPO_ROOT / "app" / "licensing").glob("*.py"),
            REPO_ROOT / "main.py",
            REPO_ROOT / "app" / "automation" / "engine.py",
            REPO_ROOT / "tools" / "license_generator.py",
            REPO_ROOT / "tools" / "owner_vault.py",
            REPO_ROOT / "tools" / "owner_generator_app.py",
            REPO_ROOT / "uiic_automation.spec",
            REPO_ROOT / "license_generator.spec",
        ]:
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

        # 4. Neither owner tool imports heavy automation / dev CLI modules
        for owner_file in (
            REPO_ROOT / "tools" / "owner_vault.py",
            REPO_ROOT / "tools" / "owner_generator_app.py",
        ):
            otxt = owner_file.read_text(encoding="utf-8")
            assert not re.search(
                r"^\s*(?:from|import)\s+(?:playwright|rapidocr_onnxruntime|app\.portals|tools\.license_generator)\b",
                otxt,
                re.MULTILINE,
            ), f"Owner tool imports excluded module: {owner_file}"
            assert "BEGIN ENCRYPTED PRIVATE KEY" not in otxt
            assert "BEGIN PRIVATE KEY" not in otxt

        # 5. PyInstaller specs enforce strict separation between client app & owner generator
        spec_text = (REPO_ROOT / "uiic_automation.spec").read_text(encoding="utf-8")
        assert '"cryptography"' in spec_text
        assert '"app.licensing"' in spec_text
        assert '"tools"' in spec_text
        assert "owner_vault" not in spec_text
        assert "owner_generator_app" not in spec_text

        owner_spec = (REPO_ROOT / "license_generator.spec").read_text(encoding="utf-8")
        assert 'APP_NAME = "UIIC_License_Generator"' in owner_spec
        assert '"owner_generator_app.py"' in owner_spec
        assert "console=False" in owner_spec
        assert '"cryptography"' in owner_spec
        assert '"tools.owner_generator_app"' in owner_spec
        for excluded_pkg in ('"playwright"', '"rapidocr_onnxruntime"', '"onnxruntime"', '"tools.license_generator"'):
            assert excluded_pkg in owner_spec

        # 6. .gitignore tracks specs while ignoring secrets/vault/license files
        gi_text = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        for line in ("!uiic_automation.spec", "!license_generator.spec", "*.pem", "*.lic", "*.uikey", "owner_vault.json", "issued_licenses.jsonl"):
            assert line in gi_text

        # 7. CI workflow builds Owner EXE only as private workflow artifact, never attached to Release
        wf_text = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
        assert "license_generator.spec" in wf_text
        assert "OWNER_ZIP_NAME" in wf_text
        release_section = wf_text.split("Create GitHub Release", 1)[1]
        assert "files: ${{ steps.version.outputs.ZIP_NAME }}.zip" in release_section
        assert "OWNER_ZIP_NAME" not in release_section

        req_text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        assert "cryptography" in req_text
        req_build_text = (REPO_ROOT / "requirements-build.txt").read_text(encoding="utf-8")
        assert "cryptography==" in req_build_text
