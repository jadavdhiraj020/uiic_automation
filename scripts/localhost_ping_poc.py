"""Disposable Base44-to-localhost connectivity proof of concept.

Standalone standard-library script. It does not import or start App-3.
"""

from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import shutil
import stat
import tempfile
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile


HOST = "127.0.0.1"
PORT = 48117
ALLOWED_ORIGIN = "https://jadav.base44.app"
TEST_ZIP_URL = "https://base44.app/api/apps/6ab74380b9e0063628bc990a/files/mp/public/6ab74380b9e0063628bc990a/2600aad8a_docwriter-helper-poc.zip"
TEST_ZIP_MEDIA_URL = "https://media.base44.com/files/public/6ab74380b9e0063628bc990a/2600aad8a_docwriter-helper-poc.zip"
LOG_PATH = Path(__file__).with_name("localhost_ping_poc.log")
MAX_BODY_BYTES = 1024
MAX_DOWNLOAD_BODY_BYTES = 4096
MAX_ZIP_BYTES = 25 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_ZIP_MEMBERS = 200
MAX_EXPANSION_RATIO = 20
TEST_MARKER = b"DOCWRITER-HELPER-POC"


class TestZipRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, new_url):
        if request.full_url == TEST_ZIP_URL and new_url == TEST_ZIP_MEDIA_URL:
            return super().redirect_request(request, fp, code, message, headers, new_url)
        return None


def validate_test_url(value: object) -> str:
    if not isinstance(value, str) or not value or len(value) > 2048:
        raise ValueError("zip_url must be a nonempty HTTPS URL")
    parsed = urlsplit(value)
    if (
        value != TEST_ZIP_URL
        or parsed.scheme != "https"
        or parsed.hostname != "base44.app"
    ):
        raise ValueError("zip_url must match the approved public test ZIP URL")
    return value


def download_test_zip(zip_url: str, destination: Path) -> None:
    request = Request(zip_url, headers={"Accept": "application/zip", "User-Agent": "DocWriter-Helper-PoC/1"})
    opener = build_opener(TestZipRedirect)
    total = 0
    with opener.open(request, timeout=20) as response, destination.open("wb") as output:
        if response.status != 200:
            raise ValueError(f"ZIP request returned HTTP {response.status}")
        content_length = response.headers.get("Content-Length")
        if content_length and int(content_length) > MAX_ZIP_BYTES:
            raise ValueError("test ZIP exceeds the 25 MiB limit")
        while True:
            chunk = response.read(64 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_ZIP_BYTES:
                raise ValueError("test ZIP exceeds the 25 MiB limit")
            output.write(chunk)
    if total == 0:
        raise ValueError("test ZIP is empty")


def extract_and_verify_test_zip(archive_path: Path, extract_root: Path) -> None:
    if not zipfile.is_zipfile(archive_path):
        raise ValueError("download is not a valid ZIP")
    extract_root.mkdir()
    seen = set()
    total_size = 0
    root = extract_root.resolve()
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        if not members or len(members) > MAX_ZIP_MEMBERS:
            raise ValueError("invalid ZIP member count")
        for member in members:
            name = member.filename
            parts = name.rstrip("/").split("/")
            if (
                not name
                or name.startswith("/")
                or "\\" in name
                or re.match(r"^[A-Za-z]:", name)
                or any(part in ("", ".", "..") for part in parts)
            ):
                raise ValueError("unsafe ZIP member path")
            normalized = "/".join(parts).casefold()
            if normalized in seen:
                raise ValueError("duplicate ZIP member path")
            seen.add(normalized)
            kind = (member.external_attr >> 16) & 0o170000
            if kind not in (0, stat.S_IFREG, stat.S_IFDIR) or (member.flag_bits & 0x1):
                raise ValueError("special or encrypted ZIP member")
            if member.file_size < 0 or member.compress_size < 0:
                raise ValueError("invalid ZIP member size")
            total_size += member.file_size
            if total_size > MAX_UNCOMPRESSED_BYTES:
                raise ValueError("test ZIP exceeds the 100 MiB extraction limit")
            if member.file_size > MAX_EXPANSION_RATIO * max(member.compress_size, 1):
                raise ValueError("test ZIP expansion ratio exceeds 20:1")
            target = extract_root.joinpath(*parts)
            if not target.resolve().is_relative_to(root):
                raise ValueError("ZIP member escapes the test folder")

        for member in members:
            target = extract_root.joinpath(*member.filename.rstrip("/").split("/"))
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as source, target.open("xb") as output:
                    shutil.copyfileobj(source, output, 64 * 1024)
                if target.stat().st_size != member.file_size:
                    raise ValueError("extracted ZIP member size mismatch")

    marker = extract_root / "test_marker.txt"
    if not marker.is_file() or marker.read_bytes() != TEST_MARKER:
        raise ValueError("test_marker.txt is missing or has incorrect content")


def log_event(event: str, origin: str, result: str) -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with LOG_PATH.open("a", encoding="utf-8") as log:
        log.write(f"{timestamp} | {event} | origin={origin!r} | {result}\n")


class PingHandler(BaseHTTPRequestHandler):
    server_version = "LocalhostPingPOC/1"

    def _allowed(self) -> bool:
        return (
            self.path in ("/ping", "/start-test")
            and self.headers.get("Origin") == ALLOWED_ORIGIN
            and self.headers.get("Host") == f"{HOST}:{PORT}"
        )

    def _send(self, status: int, body: dict | None = None, *, cors: bool = False) -> None:
        payload = b"" if body is None else json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        if cors:
            self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
            self.send_header("Vary", "Origin")
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        if payload:
            self.wfile.write(payload)

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "")
        if not self._allowed():
            self._send(403)
            log_event("OPTIONS received", origin, "403 rejected")
            return

        requested_method = self.headers.get("Access-Control-Request-Method", "")
        requested_headers = {
            item.strip().lower()
            for item in self.headers.get("Access-Control-Request-Headers", "").split(",")
            if item.strip()
        }
        if requested_method != "POST" or not requested_headers.issubset({"content-type"}):
            self._send(403)
            log_event("OPTIONS received", origin, "403 unsupported preflight")
            return

        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", ALLOWED_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "0")
        self.send_header("Vary", "Origin, Access-Control-Request-Method, Access-Control-Request-Headers")
        if self.headers.get("Access-Control-Request-Private-Network", "").lower() == "true":
            self.send_header("Access-Control-Allow-Private-Network", "true")
        if self.headers.get("Access-Control-Request-Local-Network", "").lower() == "true":
            # Compatibility with the briefly specified Local-Network header names.
            self.send_header("Access-Control-Allow-Local-Network", "true")
        self.send_header("Content-Length", "0")
        self.end_headers()
        log_event("OPTIONS received", origin, "204 preflight response sent")

    def do_POST(self) -> None:
        origin = self.headers.get("Origin", "")
        if not self._allowed():
            self._send(403)
            log_event("POST received", origin, "403 rejected")
            return

        if self.path == "/start-test":
            self._handle_download_test(origin)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 0 or length > MAX_BODY_BYTES:
                raise ValueError("invalid body length")
            body = json.loads(self.rfile.read(length)) if length else {"command": "PING"}
            if not isinstance(body, dict) or body.get("command") != "PING":
                raise ValueError("expected PING command")
        except (ValueError, UnicodeDecodeError):
            self._send(400, {"status": "error", "message": "expected PING command"}, cors=True)
            log_event("POST received", origin, "400 invalid PING; response sent")
            return

        response = {
            "status": "ok",
            "helper": "poc",
            "contract_version": 1,
            "received_at": datetime.now(timezone.utc).isoformat(),
        }
        self._send(200, response, cors=True)
        log_event("POST received", origin, "200 PING response sent")

    def _handle_download_test(self, origin: str) -> None:
        try:
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                raise ValueError("Content-Type must be application/json")
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_DOWNLOAD_BODY_BYTES:
                raise ValueError("invalid body length")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict) or body.get("command") != "DOWNLOAD_TEST":
                raise ValueError("expected DOWNLOAD_TEST command")
            run_id = body.get("run_id")
            portal_id = body.get("portal_id")
            if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", run_id):
                raise ValueError("invalid run_id")
            if portal_id not in ("uiic", "oic", "newindia"):
                raise ValueError("invalid portal_id")
            zip_url = validate_test_url(body.get("zip_url"))
        except (ValueError, UnicodeDecodeError) as exc:
            self._send(400, {"ok": False, "error": str(exc)}, cors=True)
            log_event("POST /start-test received", origin, f"400 {exc}; response sent")
            return

        test_folder = Path(tempfile.mkdtemp(prefix="docwriter-helper-poc-"))
        archive_path = test_folder / "test.zip.download"
        try:
            download_test_zip(zip_url, archive_path)
            extract_and_verify_test_zip(archive_path, test_folder / "extracted")
        except (OSError, ValueError, RuntimeError, HTTPError, URLError, zipfile.BadZipFile) as exc:
            self._send(422, {"ok": False, "error": str(exc)}, cors=True)
            log_event(
                "POST /start-test received", origin,
                f"422 {type(exc).__name__}: {exc}; response sent | run_id={run_id!r} | portal_id={portal_id!r} | test_folder={str(test_folder)!r}",
            )
            return

        self._send(200, {"ok": True, "status": "verified", "run_id": run_id}, cors=True)
        log_event(
            "POST /start-test received", origin,
            f"200 response sent | run_id={run_id!r} | portal_id={portal_id!r} | test_folder={str(test_folder)!r} | marker=verified",
        )

    def log_message(self, format: str, *args: object) -> None:
        # Request details are written only to the local POC log above.
        pass


def main() -> None:
    try:
        server = ThreadingHTTPServer((HOST, PORT), PingHandler)
    except OSError as exc:
        raise SystemExit(f"Cannot listen on {HOST}:{PORT}: {exc}") from exc
    try:
        print(f"Localhost POC listening at http://{HOST}:{PORT} (/ping, /start-test)")
        print(f"Allowed browser origin: {ALLOWED_ORIGIN}")
        print(f"Log: {LOG_PATH}")
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
