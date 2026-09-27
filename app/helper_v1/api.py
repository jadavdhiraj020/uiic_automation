"""Published Base44 page to loopback helper HTTP boundary."""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json

from .base44 import RemoteError
from .contracts import BASE44_ORIGIN, ContractError, StartRequest, parse_stop
from .coordinator import BusyError


HOST = "127.0.0.1"
PORT = 48117
ORIGIN = BASE44_ORIGIN
MAX_BODY = 16 * 1024
ROUTES = frozenset({"/ping", "/v1/start", "/v1/stop"})


class HelperServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False

    def __init__(self, coordinator, address=(HOST, PORT)):
        self.coordinator = coordinator
        super().__init__(address, HelperHandler)


class HelperHandler(BaseHTTPRequestHandler):
    server_version = "DocWriterHelperV1/1"

    def log_message(self, format, *args):
        # The normal access log may contain sensitive request data. The
        # coordinator provides sanitized run logs instead.
        return

    def _allowed(self):
        return (self.path in ROUTES and self.headers.get("Origin") == ORIGIN
                and self.headers.get("Host") == f"{HOST}:{self.server.server_port}")

    def _send(self, status, body=None, cors=True):
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        if cors and self._allowed():
            self.send_header("Access-Control-Allow-Origin", ORIGIN)
            self.send_header("Vary", "Origin")
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_OPTIONS(self):
        if not self._allowed():
            self._send(403, {"ok": False, "error": "origin or route rejected"}, cors=False)
            return
        requested = {part.strip().lower() for part in
                     self.headers.get("Access-Control-Request-Headers", "").split(",") if part.strip()}
        if self.headers.get("Access-Control-Request-Method") != "POST" or not requested.issubset({"content-type"}):
            self._send(403, {"ok": False, "error": "unsupported preflight"})
            return
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "0")
        self.send_header("Vary", "Origin, Access-Control-Request-Method, Access-Control-Request-Headers")
        if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        if self.headers.get("Access-Control-Request-Local-Network", "").lower() == "true":
            self.send_header("Access-Control-Allow-Local-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self):
        if not self._allowed():
            self._send(403, {"ok": False, "error": "origin or route rejected"}, cors=False)
            return
        try:
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ContractError("Content-Type must be application/json")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_BODY:
                raise ContractError("invalid request body length")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ContractError("request must be a JSON object")
            if self.path == "/ping":
                if body.get("command") != "PING":
                    raise ContractError("expected PING")
                self._send(200, {"status": "ok", "helper": "docwriter-uiic-v1",
                                 "contract_version": 1,
                                 "received_at": datetime.now(timezone.utc).isoformat()})
            elif self.path == "/v1/start":
                request = StartRequest.parse(body)
                self.server.coordinator.start(request)
                self._send(202, {"ok": True, "status": "accepted", "run_id": request.run_id})
            else:
                run_id, dispatch_id = parse_stop(body)
                self.server.coordinator.stop(run_id, dispatch_id)
                self._send(202, {"ok": True, "status": "accepted", "run_id": run_id})
        except (ContractError, ValueError) as exc:
            self._send(400, {"ok": False, "error": str(exc)[:300]})
        except BusyError as exc:
            self._send(409, {"ok": False, "error": str(exc)[:300]})
        except RemoteError as exc:
            # A failed launch redemption never starts Chromium or consumes the
            # coordinator slot. Keep the remote HTTP class visible to Base44.
            code = 502 if exc.status == 0 else (exc.status if 400 <= exc.status < 500 else 502)
            self._send(code, {"ok": False, "error": str(exc)[:300]})
        except Exception as exc:
            self._send(500, {"ok": False, "error": f"helper error: {type(exc).__name__}"})
