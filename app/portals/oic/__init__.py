# app/portals/oic/__init__.py
from .automation.login_module import do_login
from .automation.navigation_module import navigate_to_claim
from .automation.claim_assessment_module import fill_claim_assessment_details
from .automation.document_upload_module import fill_document_upload_section

__all__ = [
    "do_login",
    "navigate_to_claim",
    "fill_claim_assessment_details",
    "fill_document_upload_section",
]