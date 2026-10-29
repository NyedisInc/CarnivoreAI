
from __future__ import annotations

import base64
import socket
import ssl
import subprocess
import threading
from pathlib import Path
from typing import Optional


def make_cert(directory: Path, hostname: str) -> tuple[Path, Path]:
    cert, key = directory / "c.pem", directory / "k.pem"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(cert), "-days", "2", "-subj", f"/CN={hostname}",
         "-addext", f"subjectAltName=DNS:{hostname}"],
        check=True, capture_output=True,
    )
    return cert, key


class FakeSMTP:

    def __init__(self, *, cert: Optional[tuple[Path, Path]] = None, implicit_tls: bool = False,
                 offer_starttls: bool = False, auth_ok: bool = True, rcpt_reply: str = "250 ok") -> None:
        self.ctx = None
        if cert:
            self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self.ctx.load_cert_chain(str(cert[0]), str(cert[1]))
        self.implicit_tls, self.offer_starttls = implicit_tls, offer_starttls
        self.auth_ok, self.rcpt_reply = auth_ok, rcpt_reply
        self.mail_from = ""
        self.rcpts: list[str] = []
        self.data = ""
        self.login: Optional[bytes] = None
        self.connections = 0
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(4)
        self.port = self.sock.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self) -> None:
        self.sock.close()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            self.connections += 1
            try:
                self._session(conn)
            except (OSError, ssl.SSLError):
                pass
            finally:
                conn.close()

    def _session(self, conn: socket.socket) -> None:
        if self.implicit_tls:
            conn = self.ctx.wrap_socket(conn, server_side=True)
        f = conn.makefile("rwb", buffering=0)
        send = lambda s: f.write((s + "\r\n").encode())
        send("220 fake ready")
        in_data = False
        lines: list[str] = []
        while True:
            raw = f.readline()
            if not raw:
                return
            line = raw.decode().rstrip("\r\n")
            if in_data:
                if line == ".":
                    self.data = "\n".join(lines)
                    in_data = False
                    send("250 queued")
                else:
                    lines.append(line[1:] if line.startswith("..") else line)
                continue
            cmd = line.upper()
            if cmd.startswith("EHLO"):
                send("250-fake")
                if self.offer_starttls and not isinstance(conn, ssl.SSLSocket):
                    send("250-STARTTLS")
                send("250 AUTH PLAIN")
            elif cmd == "STARTTLS":
                send("220 go")
                conn = self.ctx.wrap_socket(conn, server_side=True)
                f = conn.makefile("rwb", buffering=0)
                send = lambda s, f=f: f.write((s + "\r\n").encode())
            elif cmd.startswith("AUTH PLAIN"):
                self.login = base64.b64decode(line.split()[2])
                send("235 ok" if self.auth_ok else "535 bad credentials")
            elif cmd.startswith("MAIL FROM"):
                self.mail_from = line[10:].strip().strip("<>").split(">")[0]
                send("250 ok")
            elif cmd.startswith("RCPT TO"):
                reply = self.rcpt_reply
                if reply.startswith("2"):
                    self.rcpts.append(line[8:].strip().strip("<>").split(">")[0])
                send(reply)
            elif cmd == "DATA":
                in_data = True
                send("354 go")
            elif cmd == "QUIT":
                send("221 bye")
                return
            else:
                send("250 ok")
