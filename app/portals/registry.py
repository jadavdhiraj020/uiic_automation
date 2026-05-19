"""
registry.py — Central registry for all supported portals.

Provides:
  - Portal definitions (name, URL, display label, config directory)
  - Active portal state management (get/set)
  - Config-path resolution per portal

Backward Compatibility:
  - When no portal is explicitly set, all config resolution defaults to the
    original ``app/config/`` directory.  This means the existing UIIC
    workflow works IDENTICALLY without any portal selection.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.utils import resource_path, user_data_dir


# ─────────────────────────────────────────────────────────────────────────────
# Portal Definition
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class PortalInfo:
    """Immutable descriptor for a supported insurance portal."""
    portal_id: str              # Machine-readable key  e.g. "uiic"
    display_name: str           # Human label            e.g. "UIIC (United India)"
    url: str                    # Default portal URL
    config_subdir: str          # Relative to app/portals/<id>/config/
    description: str = ""       # Short tooltip text

    # ── Portal capability flags ──────────────────────────────────────────────
    # These flags describe what the portal requires from shared services like
    # folder_scanner.py. Add new flags here as portal-specific needs grow.
    # The scanner/UI reads these flags and adjusts behaviour accordingly,
    # keeping portal-specific logic OUT of shared, generic code.

    requires_document_merge: bool = False
    """
    When True, the folder scanner will pre-merge all leftover (unmatched)
    documents into a single 'claim_others_documents.pdf' during the scan
    phase. This is required by portals (e.g. New India) that only accept
    a single 'Claim Related' upload slot.

    When False (default), no merge is performed and the pre-merged PDF is
    never created, keeping the claim folder clean for portals (e.g. UIIC)
    that handle individual document uploads directly.
    """

    # ── derived paths ──
    def bundled_config_dir(self) -> str:
        """Read-only config shipped inside the app bundle."""
        return resource_path("app", "portals", self.portal_id, "config")

    def user_config_dir(self) -> str:
        """Writable per-user config in AppData."""
        return os.path.join(user_data_dir("portals", self.portal_id), "config")


# ─────────────────────────────────────────────────────────────────────────────
# Registry — all known portals
# ─────────────────────────────────────────────────────────────────────────────

_PORTALS: Dict[str, PortalInfo] = {}

def register_portal(info: PortalInfo) -> None:
    """Register a portal definition (called once per portal at import time)."""
    _PORTALS[info.portal_id] = info

def get_portal(portal_id: str) -> Optional[PortalInfo]:
    return _PORTALS.get(portal_id)

def list_portals() -> List[PortalInfo]:
    """Return all registered portals in display order."""
    return list(_PORTALS.values())


# ─────────────────────────────────────────────────────────────────────────────
# Active portal state  (global singleton — thread-safe for single-UI apps)
# ─────────────────────────────────────────────────────────────────────────────

_active_portal_id: Optional[str] = None

def set_active_portal(portal_id: str) -> None:
    """Set the currently selected portal.  Called from the UI dropdown."""
    global _active_portal_id
    if portal_id not in _PORTALS:
        raise ValueError(f"Unknown portal: {portal_id!r}. Registered: {list(_PORTALS.keys())}")
    _active_portal_id = portal_id

def get_active_portal() -> Optional[PortalInfo]:
    """Return the currently selected portal, or None if unset."""
    if _active_portal_id is None:
        return None
    return _PORTALS.get(_active_portal_id)

def get_active_portal_id() -> Optional[str]:
    return _active_portal_id


# ─────────────────────────────────────────────────────────────────────────────
# Config path helpers  (portal-aware equivalents of utils.py functions)
# ─────────────────────────────────────────────────────────────────────────────

def portal_settings_paths(portal_id: Optional[str] = None) -> dict:
    """
    Return ``{"default": ..., "user": ...}`` settings paths for a portal.

    Falls back to the original ``app/config/`` paths when portal_id is None,
    preserving full backward compatibility.
    """
    if portal_id is None:
        portal_id = _active_portal_id

    if portal_id is None:
        # No portal selected → original behavior
        return {
            "default": resource_path("app", "config", "settings.json"),
            "user":    os.path.join(user_data_dir("config"), "settings.json"),
        }

    info = _PORTALS.get(portal_id)
    if info is None:
        raise ValueError(f"Unknown portal: {portal_id!r}")

    return {
        "default": os.path.join(info.bundled_config_dir(), "settings.json"),
        "user":    os.path.join(info.user_config_dir(), "settings.json"),
    }


def portal_field_mapping_paths(portal_id: Optional[str] = None) -> dict:
    if portal_id is None:
        portal_id = _active_portal_id

    if portal_id is None:
        return {
            "default": resource_path("app", "config", "field_mapping.json"),
            "user":    os.path.join(user_data_dir("config"), "field_mapping.json"),
        }

    info = _PORTALS.get(portal_id)
    if info is None:
        raise ValueError(f"Unknown portal: {portal_id!r}")

    return {
        "default": os.path.join(info.bundled_config_dir(), "field_mapping.json"),
        "user":    os.path.join(info.user_config_dir(), "field_mapping.json"),
    }


def portal_doc_mapping_paths(portal_id: Optional[str] = None) -> dict:
    if portal_id is None:
        portal_id = _active_portal_id

    if portal_id is None:
        return {
            "default": resource_path("app", "config", "doc_mapping.json"),
            "user":    os.path.join(user_data_dir("config"), "doc_mapping.json"),
        }

    info = _PORTALS.get(portal_id)
    if info is None:
        raise ValueError(f"Unknown portal: {portal_id!r}")

    return {
        "default": os.path.join(info.bundled_config_dir(), "doc_mapping.json"),
        "user":    os.path.join(info.user_config_dir(), "doc_mapping.json"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Auto-register bundled portals
# ─────────────────────────────────────────────────────────────────────────────

register_portal(PortalInfo(
    portal_id="uiic",
    display_name="UIIC (United India)",
    url="https://portal.uiic.in/surveyor/home.jsp",
    config_subdir="config",
    description="United India Insurance Company — Surveyor Portal",
    requires_document_merge=False,  # UIIC accepts individual document slots
))

register_portal(PortalInfo(
    portal_id="newindia",
    display_name="New India Assurance",
    url="https://web.newindia.co.in/NIABancsPortal/IntermediaryLogin.html",
    config_subdir="config",
    description="New India Assurance Company — Intermediary Portal",
    requires_document_merge=True,   # NIA has a single 'Claim Related' upload slot
))
