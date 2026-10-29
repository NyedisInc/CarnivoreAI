
from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.parse
from typing import Any, Dict, List, Optional

CLIENT_ID = "123-abc.apps.googleusercontent.com"
CLIENT_SECRET = "GOCSPX-test-not-real"
WEB_CLIENT_ID = "456-web.apps.googleusercontent.com"
WEB_CLIENT_SECRET = "GOCSPX-web-test-not-real"
WEB_REDIRECT_URI = "https://api.carnivore.ai/v1/auth/callback/google"


def id_token(claims: Dict[str, Any]) -> str:
    def part(obj: Dict[str, Any]) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS256'})}.{part(claims)}.sig"


class _Response:

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


class FakeGoogle:

    def __init__(self, now: int) -> None:
        self.now = now
        self.answer = "ok"
        self.claims: Dict[str, Any] = {}
        self.calls: List[Any] = []
        self.web_challenge = ""
        self.web_nonce = ""

    def token_claims(self, **override: Any) -> Dict[str, Any]:
        base = {
            "iss": "https://accounts.google.com", "aud": CLIENT_ID, "exp": self.now + 3600,
            "sub": "108000000000000000001", "email": "person@example.com", "email_verified": True,
            "hd": "example.com",
        }
        base.update(self.claims)
        base.update(override)
        return base

    def urlopen(self, request: Any, timeout: Any = None) -> _Response:
        fields = {k: v[0] for k, v in urllib.parse.parse_qs(request.data.decode()).items()}
        self.calls.append((request.full_url, fields))
        if request.full_url == "https://oauth2.googleapis.com/device/code":
            assert fields.get("scope") == "openid email", fields
            return _Response({
                "device_code": "dev-code", "user_code": "ABC-DEF-GHI", "expires_in": 1800,
                "interval": 5, "verification_url": "https://www.google.com/device",
            })
        if request.full_url != "https://oauth2.googleapis.com/token":
            raise ValueError(f"the fake google was asked for {request.full_url!r}")
        if fields.get("grant_type") == "authorization_code":
            return self._web_exchange(fields)
        if fields.get("client_secret") != CLIENT_SECRET or fields.get("client_id") != CLIENT_ID:
            raise self._error(401, "invalid_client")
        if self.answer == "ok":
            return _Response({"access_token": "ya29.x", "id_token": id_token(self.token_claims())})
        status = {"pending": 428, "slow_down": 403}.get(self.answer, 400)
        raise self._error(status, "authorization_pending" if self.answer == "pending" else self.answer)

    def _web_exchange(self, fields: Dict[str, str]) -> _Response:
        import hashlib
        if fields.get("client_secret") != WEB_CLIENT_SECRET or fields.get("client_id") != WEB_CLIENT_ID:
            raise self._error(401, "invalid_client")
        if fields.get("redirect_uri") != WEB_REDIRECT_URI or fields.get("code") != "web-code":
            raise self._error(400, "invalid_grant")
        challenge = base64.urlsafe_b64encode(
            hashlib.sha256(fields.get("code_verifier", "").encode()).digest()).decode().rstrip("=")
        if challenge != self.web_challenge:
            raise self._error(400, "invalid_grant")
        claims = self.token_claims(aud=WEB_CLIENT_ID, nonce=self.web_nonce)
        return _Response({"access_token": "ya29.web", "id_token": id_token(claims)})

    @staticmethod
    def _error(status: int, error: str) -> urllib.error.HTTPError:
        return urllib.error.HTTPError(
            "https://oauth2.googleapis.com/token", status, error, {},
            io.BytesIO(json.dumps({"error": error}).encode()),
        )
