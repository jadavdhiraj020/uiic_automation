import logging
from dataclasses import dataclass
from typing import Callable, Dict, Optional


logger = logging.getLogger(__name__)


@dataclass
class ChequeOcrResult:
    details: Dict[str, str]
    status: str
    message: str = ""


class BaseChequeOcrAdapter:
    portal_id = "shared"

    def extract_details(
        self,
        cheque_path: str,
        *,
        log: Optional[Callable[[str], None]] = None,
        excel_ifsc: str = "",
        excel_account: str = "",
        stop_cb: Optional[Callable[[], bool]] = None,
    ) -> ChequeOcrResult:
        message = f"Cheque OCR is not configured for portal '{self.portal_id}'."
        if log:
            log(message)
        return ChequeOcrResult({}, "unsupported", message)


class NewIndiaChequeOcrAdapter(BaseChequeOcrAdapter):
    portal_id = "newindia"

    def extract_details(
        self,
        cheque_path: str,
        *,
        log: Optional[Callable[[str], None]] = None,
        excel_ifsc: str = "",
        excel_account: str = "",
        stop_cb: Optional[Callable[[], bool]] = None,
    ) -> ChequeOcrResult:
        from app.portals.newindia.automation.ocr_helper import ChequeExtractor

        extractor = ChequeExtractor(cheque_path)
        details = extractor.extract_details(
            log=log,
            excel_ifsc=excel_ifsc,
            excel_account=excel_account,
            stop_cb=stop_cb,
        )
        return ChequeOcrResult(details or {}, "success")


class UnsupportedChequeOcrAdapter(BaseChequeOcrAdapter):
    def __init__(self, portal_id: str):
        self.portal_id = portal_id or "uiic"


def get_cheque_ocr_adapter(portal_id: str) -> BaseChequeOcrAdapter:
    normalized = (portal_id or "uiic").lower()
    if normalized == "newindia":
        return NewIndiaChequeOcrAdapter()
    return UnsupportedChequeOcrAdapter(normalized)
