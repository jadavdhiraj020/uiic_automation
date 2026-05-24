# app/portals/oic/__init__.py
from .automation.login_module import do_login
from .automation.navigation_module import navigate_to_claim
from .automation.claim_search_module import fill_claim_search

__all__ = [
    "do_login",
    "navigate_to_claim",
    "fill_claim_search",
]