
from __future__ import annotations

import base64
import hashlib
import io
import json
import urllib.error
import urllib.parse
from typing import Any, Dict, List

CLIENT_ID = "Ov23li-test-not-real"
CLIENT_SECRET = "gh-secret-test-not-real"
REDIRECT_URI = "https://api.carnivore.ai/v1/auth/callback/github"
TOKEN = "gho_fake_user_token"


class _Response:

    def __init__(self, payload: Any) -> None:
        self._raw = json.dumps(payload).encode()

    def read(self, *_a: Any) -> bytes:
        return self._raw

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


class FakeGitHub:

    def __init__(self) -> None:
        self.user: Dict[str, Any] = {"id": 424242, "login": "octo"}
        self.emails: List[Dict[str, Any]] = [
            {"email": "Person@Example.com", "primary": True, "verified": True},
            {"email": "424242+octo@users.noreply.github.com", "primary": False, "verified": True},
        ]
        self.challenge = ""
        self.calls: List[str] = []

    def urlopen(self, request: Any, timeout: Any = None) -> _Response:
        url = request.full_url
        self.calls.append(url)
        if url == "https://github.com/login/oauth/access_token":
            fields = {k: v[0] for k, v in urllib.parse.parse_qs(request.data.decode()).items()}
            digest = hashlib.sha256(fields.get("code_verifier", "").encode()).digest()
            ok = (fields.get("client_id") == CLIENT_ID and fields.get("client_secret") == CLIENT_SECRET
                  and fields.get("redirect_uri") == REDIRECT_URI and fields.get("code") == "gh-code"
                  and base64.urlsafe_b64encode(digest).decode().rstrip("=") == self.challenge)
            return _Response({"access_token": TOKEN, "token_type": "bearer"} if ok
                             else {"error": "bad_verification_code"})
        if request.get_header("Authorization") != f"Bearer {TOKEN}":
            raise urllib.error.HTTPError(url, 401, "unauthorized", {}, io.BytesIO(b"{}"))
        if url == "https://api.github.com/user":
            return _Response(self.user)
        if url == "https://api.github.com/user/emails":
            return _Response(self.emails)
        raise ValueError(f"the fake github was asked for {url!r}")
