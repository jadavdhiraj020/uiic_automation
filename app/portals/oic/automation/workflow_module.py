# app/portals/oic/automation/workflow_module.py
"""
workflow_module.py — OIC Automation Workflow Step Blueprint.

Defines the logging categories and future integration steps.
"""

import logging

logger = logging.getLogger(__name__)

# ── LOGGING CATEGORIES ────────────────────────────────────────────────────────
# These tags help filter and organize logs during real-time UI logging.
EXTRACTION = "EXTRACTION"
VALIDATION = "VALIDATION"
NAVIGATION = "NAVIGATION"
OCR        = "OCR"
UPLOAD     = "UPLOAD"
WORKFLOW   = "WORKFLOW"
ERROR      = "ERROR_RETRY"

class OicWorkflowTracker:
    """Blueprint for OIC step tracking and workflow orchestration."""
    def __init__(self, log_cb):
        self.log_cb = log_cb

    def log_extraction(self, message: str):
        self.log_cb(f"🔍 [{EXTRACTION}] {message}")

    def log_validation(self, message: str):
        self.log_cb(f"✅ [{VALIDATION}] {message}")

    def log_navigation(self, message: str):
        self.log_cb(f"🌐 [{NAVIGATION}] {message}")

    def log_ocr(self, message: str):
        self.log_cb(f"👁️ [{OCR}] {message}")

    def log_upload(self, message: str):
        self.log_cb(f"📄 [{UPLOAD}] {message}")

    def log_workflow(self, message: str):
        self.log_cb(f"⚙️ [{WORKFLOW}] {message}")

    def log_error(self, message: str):
        self.log_cb(f"🚨 [{ERROR}] {message}")