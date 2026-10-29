import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CLIENT = os.path.join(REPO_ROOT, "client")
THEMES = os.path.join(CLIENT, "css", "themes")

MIME = {
    ".html": "text/html", ".js": "text/javascript", ".css": "text/css",
    ".json": "application/json", ".png": "image/png", ".svg": "image/svg+xml",
    ".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf",
    ".webmanifest": "application/manifest+json", ".map": "application/json",
    ".mjs": "text/javascript", ".ico": "image/x-icon",
}


def manifests():
    out = []
    for name in sorted(os.listdir(THEMES)):
        path = os.path.join(THEMES, name, "theme.json")
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as fh:
            manifest = json.load(fh)
        manifest["source"] = "builtin"
        manifest.setdefault("id", name)
        out.append(manifest)
    return out


class Handler(BaseHTTPRequestHandler):

    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):  # noqa: N802
        path = self.path.split("?")[0]
        if path == "/api/v1/themes":
            self._send(200, json.dumps(manifests()).encode(), "application/json")
            return
        if path.startswith("/api/"):
            self._send(200, b"[]", "application/json")
            return
        if path in ("/", "/index.html"):
            target = os.path.join(CLIENT, "index.html")
        elif path.startswith("/static/"):
            target = os.path.join(CLIENT, *path[len("/static/"):].split("/"))
        else:
            target = os.path.join(CLIENT, *path.lstrip("/").split("/"))
        target = os.path.normpath(target)
        if not target.startswith(CLIENT) or not os.path.isfile(target):
            self._send(404, b"not found", "text/plain")
            return
        ext = os.path.splitext(target)[1]
        with open(target, "rb") as fh:
            self._send(200, fh.read(), MIME.get(ext, "application/octet-stream"))


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5057
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
