"""Base44 V1 calls. No App-3 operator login or old app-ID route is used."""

from pathlib import Path
import os
import requests
import threading

from .contracts import ContractError, parse_redemption


class RemoteError(RuntimeError):
    def __init__(self, operation, status, message, code=""):
        super().__init__(f"{operation}: HTTP {status}: {message}")
        self.operation = operation
        self.status = status
        self.code = code


def _response_error(operation, response):
    try:
        body = response.json()
    except ValueError:
        body = {}
    detail = body.get("message") or body.get("error") or response.reason or "request failed"
    error = RemoteError(operation, response.status_code, str(detail)[:300])
    error.code = str(body.get("code") or body.get("error") or "").strip().lower()
    return error


class Base44V1Client:
    def __init__(self, session=None):
        self._injected_session = session
        self._thread_local = threading.local()

    @property
    def session(self):
        if self._injected_session is not None:
            return self._injected_session
        if not hasattr(self._thread_local, "session"):
            self._thread_local.session = requests.Session()
        return self._thread_local.session

    def redeem(self, start):
        url = f"{start.api_base}/functions/validateLaunchToken"
        try:
            response = self.session.post(url, json={"run_id": start.run_id,
                "dispatch_id": start.dispatch_id, "launch_token": start.launch_token},
                # Keep redemption bounded below Base44's eight-second browser
                # request timeout; the run itself starts asynchronously after this.
                timeout=(2, 4), allow_redirects=False)
        except requests.RequestException as exc:
            raise RemoteError("validateLaunchToken", 0, type(exc).__name__) from exc
        if response.status_code != 200:
            raise _response_error("validateLaunchToken", response)
        try:
            return parse_redemption(start, response.json())
        except (ValueError, ContractError) as exc:
            raise ContractError(f"invalid launch redemption response: {exc}") from exc

    def download_zip(self, context, destination, stop_requested=lambda: False):
        destination = Path(destination)
        try:
            with self.session.post(context.zip_endpoint, json={"run_id": context.run_id,
                    "dispatch_id": context.dispatch_id, "run_token": context.run_token},
                    stream=True, timeout=(5, 120), allow_redirects=False) as response:
                if response.status_code != 200:
                    raise _response_error("helperDownloadRunZip", response)
                if "zip" not in response.headers.get("Content-Type", "").lower():
                    raise ContractError("helperDownloadRunZip did not return application/zip")
                with destination.open("xb") as output:
                    for chunk in response.iter_content(1024 * 1024):
                        if stop_requested():
                            raise InterruptedError("ZIP download stopped")
                        if chunk:
                            output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
        except requests.RequestException as exc:
            destination.unlink(missing_ok=True)
            raise RemoteError("helperDownloadRunZip", 0, type(exc).__name__) from exc
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if destination.stat().st_size == 0:
            destination.unlink(missing_ok=True)
            raise ContractError("helperDownloadRunZip returned an empty ZIP")

    def callback(self, context, event):
        body = {"run_id": context.run_id, "dispatch_id": context.dispatch_id,
                "run_token": context.run_token, **event}
        try:
            response = self.session.post(context.callback_endpoint, json=body,
                                         timeout=(5, 15), allow_redirects=False)
        except requests.RequestException as exc:
            raise RemoteError("helperRunCallback", 0, type(exc).__name__) from exc
        if response.status_code != 200:
            raise _response_error("helperRunCallback", response)
        try:
            payload = response.json()
        except ValueError as exc:
            raise ContractError("helperRunCallback response is not JSON") from exc
        if payload.get("ok") is not True and payload.get("duplicate") is not True:
            raise ContractError("helperRunCallback did not acknowledge the event")
        return payload
