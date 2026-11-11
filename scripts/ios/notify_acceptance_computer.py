#!/usr/bin/env python3
import tempfile, base64, http.server, json, pathlib, struct, subprocess, sys, threading, time, zlib

ROOT = pathlib.Path(__file__).resolve().parents[2]
VECTORS = ROOT / "ios/Shared/TestVectors/notify_payload_vectors.json"
FIXTURES = ROOT / "tests/fixtures/notify_cards"
BUNDLE = "ai.carnivore.ios"
current = {"kind": ""}
VIDEO = pathlib.Path(tempfile.gettempdir()) / "carnivore-acceptance-video.mp4"


def png(w: int, h: int) -> bytes:
    raw = b"".join(b"\x00" + bytes(v for x in range(w) for v in (40 + 120 * x // w, 90 + 100 * y // h, 160)) for y in range(h))
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, status: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/v1/notify/card"):
            f = FIXTURES / f"{current['kind']}.json"
            if not f.exists():
                return self._send(404, b"{}")
            fixture = json.loads(f.read_text())
            card = fixture.get("full") or fixture["card"]
            if current["kind"] == "swarm":
                card = {**card, "positions": [[*p[:2], side] for p, side in zip(card.get("positions", []), ("studio", "nostromo"))]}
            return self._send(200, json.dumps(card).encode())
        if self.path.startswith("/api/v1/notify/media/"):
            if "/m_2" in self.path and not self.path.endswith("/poster"):
                return self._send(200, VIDEO.read_bytes(), "video/mp4") if VIDEO.exists() else self._send(404, b"{}")
            return self._send(200, png(390, 844), "image/png")
        self._send(404, b"{}")

    def do_POST(self):
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self._send(200, b'{"ok":true}')


def push(shots: pathlib.Path, kind: str, cases: dict) -> None:
    blob = base64.b64encode(bytes.fromhex(cases[kind]["ciphertext"])).decode()
    tmp = shots / f".play-{kind}"
    tmp.write_text(json.dumps({"p": blob}))
    tmp.rename(shots / f"play-{kind}.json")


def main() -> None:
    shots, udid, port, kinds = pathlib.Path(sys.argv[1]), sys.argv[2], int(sys.argv[3]), sys.argv[4].split(",")
    cases = {c["name"]: c for c in json.loads(VECTORS.read_text())["cases"]}
    if not VIDEO.exists():
        subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=390x844:rate=15:duration=3", "-pix_fmt", "yuv420p", str(VIDEO)], check=False)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for kind in kinds:
        want = shots / f"want-{kind}"
        deadline = time.time() + 900
        while not want.exists() and time.time() < deadline:
            time.sleep(0.3)
        current["kind"] = kind
        push(shots, kind, cases)
        while not (shots / f"delivered-{kind}").exists():
            time.sleep(0.2)
        (shots / f"pushed-{kind}").touch()
        print("pushed", kind, flush=True)
    time.sleep(2)


main()
