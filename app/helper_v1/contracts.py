"""Strict V1 request and redeemed-run identities."""

from dataclasses import dataclass, field
from urllib.parse import urlsplit
import re


class ContractError(ValueError):
    pass


BASE44_ORIGIN = "https://jadav-uiic-test.base44.app"


def _required(value, name, limit=256):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ContractError(f"{name} is required")
    return value.strip()


def api_origin(value):
    value = _required(value, "api_base", 512)
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname != "jadav-uiic-test.base44.app"
            or parsed.port is not None or parsed.username or parsed.password
            or parsed.path not in ("", "/", "/functions", "/functions/") or parsed.query or parsed.fragment):
        raise ContractError("api_base must be the published Base44 HTTPS origin")
    return BASE44_ORIGIN


@dataclass(frozen=True)
class StartRequest:
    run_id: str
    dispatch_id: str
    portal_id: str
    case_ref: str
    launch_token: str = field(repr=False)
    api_base: str = ""

    @classmethod
    def parse(cls, body):
        if not isinstance(body, dict) or body.get("command") != "START_RUN" or body.get("contract_version") != 1:
            raise ContractError("expected START_RUN contract version 1")
        run_id = _required(body.get("run_id"), "run_id", 128)
        dispatch_id = _required(body.get("dispatch_id"), "dispatch_id", 128)
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", run_id):
            raise ContractError("run_id has invalid characters")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", dispatch_id):
            raise ContractError("dispatch_id has invalid characters")
        if body.get("portal_id") != "uiic":
            raise ContractError("V1 supports only portal_id uiic")
        return cls(run_id, dispatch_id, "uiic", _required(body.get("case_ref"), "case_ref", 256),
                   _required(body.get("launch_token"), "launch_token", 4096), api_origin(body.get("api_base")))


@dataclass(frozen=True)
class RunContext:
    run_id: str
    dispatch_id: str
    portal_id: str
    case_ref: str
    api_base: str
    run_token: str = field(repr=False)
    portal_username: str = field(repr=False)
    portal_password: str = field(repr=False)
    surveyor_code: str = field(repr=False)
    zip_endpoint: str = ""
    callback_endpoint: str = ""


def parse_redemption(start, body):
    if (not isinstance(body, dict) or body.get("ok") is not True
            or body.get("contract_version") != 1
            or body.get("run_id") != start.run_id
            or body.get("dispatch_id") != start.dispatch_id):
        raise ContractError("launch redemption did not match this run and dispatch")
    for name, suffix in (("zip_endpoint", "helperDownloadRunZip"),
                         ("callback_endpoint", "helperRunCallback")):
        if body.get(name) != f"{start.api_base}/functions/{suffix}":
            raise ContractError(f"{name} does not match the Base44 V1 origin")
    return RunContext(start.run_id, start.dispatch_id, start.portal_id, start.case_ref, start.api_base,
                      _required(body.get("run_token"), "run_token", 4096),
                      _required(body.get("portal_username"), "portal_username", 256),
                      _required(body.get("portal_password"), "portal_password", 4096),
                      str(body.get("surveyor_code") or ""), body["zip_endpoint"], body["callback_endpoint"])


def parse_stop(body):
    if not isinstance(body, dict) or body.get("command") != "STOP_RUN" or body.get("contract_version") != 1:
        raise ContractError("expected STOP_RUN contract version 1")
    return _required(body.get("run_id"), "run_id", 128), _required(body.get("dispatch_id"), "dispatch_id", 128)
