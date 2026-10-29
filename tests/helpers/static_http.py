
from __future__ import annotations

import contextlib
import gzip
import hashlib
import ssl
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Set, Tuple

DEFAULT_SLOW_SECONDS = 3.0


@dataclass
class StaticServer:

    base_url: str
    root: Path
    redirect_paths: Set[str] = field(default_factory=set)
    status_overrides: Dict[str, int] = field(default_factory=dict)
    gzip_paths: Set[str] = field(default_factory=set)
    slow_paths: Set[str] = field(default_factory=set)
    always_304_paths: Set[str] = field(default_factory=set)
    etag_overrides: Dict[str, str] = field(default_factory=dict)
    slow_seconds: float = DEFAULT_SLOW_SECONDS
    requests: List[str] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, path: str) -> None:
        with self._lock:
            self.requests.append(path)

    def seen(self) -> List[str]:
        with self._lock:
            return list(self.requests)


def etag_for(body: bytes) -> str:
    return '"' + hashlib.sha256(body).hexdigest()[:16] + '"'


def self_signed_cert(directory: Path) -> Optional[Tuple[Path, Path]]:
    try:
        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: PLC0415
        from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: PLC0415
        from cryptography.x509.oid import NameOID  # noqa: PLC0415
    except ImportError:
        return None

    import datetime as _dt  # noqa: PLC0415
    import ipaddress as _ip  # noqa: PLC0415

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "127.0.0.1")]
    )
    now = _dt.datetime.now(_dt.timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=5))
        .not_valid_after(now + _dt.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(_ip.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None), critical=True
        )
        .sign(key, hashes.SHA256())
    )

    cert_path = directory / "static_http_cert.pem"
    key_path = directory / "static_http_key.pem"
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


def _resolve_under(root: Path, request_path: str) -> Optional[Path]:
    clean = request_path.split("?", 1)[0].lstrip("/")
    candidate = (root / clean).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _build_handler(server_state: StaticServer) -> type:

    class Handler(BaseHTTPRequestHandler):

        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _send(
            self,
            status: int,
            body: bytes,
            headers: Optional[Dict[str, str]] = None,
        ) -> None:
            try:
                self.send_response(status)
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                if body:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True

        def do_GET(self) -> None:  # noqa: N802
            path = self.path
            server_state.record(path)

            if path in server_state.slow_paths:
                time.sleep(server_state.slow_seconds)

            if path in server_state.redirect_paths:
                self._send(
                    302,
                    b"",
                    {"Location": f"{server_state.base_url}/moved{path}"},
                )
                return

            override = server_state.status_overrides.get(path)
            if override is not None:
                self._send(
                    override,
                    f"status {override}".encode("ascii"),
                    {"Content-Type": "text/plain"},
                )
                return

            target = _resolve_under(server_state.root, path)
            if target is None:
                self._send(404, b"not found", {"Content-Type": "text/plain"})
                return

            raw = target.read_bytes()
            tag = server_state.etag_overrides.get(path, etag_for(raw))
            if path in server_state.always_304_paths:
                self._send(304, b"", {"ETag": tag})
                return
            if self.headers.get("If-None-Match") == tag:
                self._send(304, b"", {"ETag": tag})
                return

            headers = {"Content-Type": "application/json", "ETag": tag}
            body = raw
            if path in server_state.gzip_paths:
                body = gzip.compress(raw)
                headers["Content-Encoding"] = "gzip"
            self._send(200, body, headers)

    return Handler


@contextlib.contextmanager
def serve_directory(
    root: Path,
    *,
    tls_cert: Optional[Tuple[Path, Path]] = None,
) -> Iterator[StaticServer]:
    state = StaticServer(base_url="", root=root)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _build_handler(state))
    httpd.daemon_threads = True

    scheme = "http"
    if tls_cert is not None:
        cert_path, key_path = tls_cert
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certfile=str(cert_path), keyfile=str(key_path))
        httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    state.base_url = f"{scheme}://127.0.0.1:{httpd.server_address[1]}"
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield state
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5.0)
