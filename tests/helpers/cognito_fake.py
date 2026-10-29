
from __future__ import annotations

import io
import json
import urllib.error
from typing import Any, Dict, List, Optional

DEFAULT_CODE = "12345678"

KNOWN_TARGETS = (
    "InitiateAuth", "RespondToAuthChallenge", "GetUser", "RevokeToken",
)


class UsernameExistsException(Exception):
    pass


class _Response:

    def __init__(self, payload: Dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: Any) -> bool:
        return False


def _error(type_name: str, message: str = "refused") -> urllib.error.HTTPError:
    body = json.dumps({"__type": type_name, "message": message}).encode("utf-8")
    return urllib.error.HTTPError(
        "https://cognito-idp.us-east-1.amazonaws.com/",
        400,
        type_name,
        {},
        io.BytesIO(body),
    )


class FakeCognito:

    def __init__(self) -> None:
        self.users: Dict[str, str] = {}
        self.disabled: set = set()
        self.sessions: Dict[str, Dict[str, Any]] = {}
        self.access_tokens: Dict[str, str] = {}
        self.refresh_tokens: Dict[str, str] = {}
        self.revoked: List[str] = []
        self.calls: List[Any] = []
        self.code = DEFAULT_CODE
        self.refusals: Dict[str, List[str]] = {}
        self.create_error: Optional[BaseException] = None
        self.username_override: Optional[str] = None
        self.email_override: Optional[str] = None
        self._counter = 0


    def refuse(self, target: str, type_name: str, times: int = 1) -> None:
        self.refusals.setdefault(target, []).extend([type_name] * times)

    def targets(self) -> List[str]:
        return [name for name, _payload in self.calls]

    def payload(self, target: str) -> Dict[str, Any]:
        for name, body in self.calls:
            if name == target:
                return body
        return {}

    def _next_id(self, shape: str) -> str:
        self._counter += 1
        return shape % self._counter

    def _sub_for(self, email: str) -> str:
        if email not in self.users:
            self._counter += 1
            self.users[email] = (
                f"{self._counter:08x}-0000-4000-8000-{self._counter:012x}"
            )
        return self.users[email]


    def admin_create_user(self, **kwargs: Any) -> Dict[str, Any]:
        self.calls.append(("AdminCreateUser", kwargs))
        if self.create_error is not None:
            raise self.create_error
        email = kwargs.get("Username", "")
        if email in self.users:
            raise UsernameExistsException("User account already exists")
        return {"User": {"Username": self._sub_for(email)}}


    def urlopen(self, request: Any, timeout: Any = None) -> _Response:
        headers = {key.lower(): value for key, value in request.headers.items()}
        target = str(headers.get("x-amz-target", ""))
        if headers.get("content-type") != "application/x-amz-json-1.1":
            raise ValueError(
                f"the fake cognito was sent content type "
                f"{headers.get('content-type')!r}"
            )
        operation = target.rsplit(".", 1)[-1] if target else ""
        if operation not in KNOWN_TARGETS:
            raise ValueError(
                f"the fake cognito was asked for the unstubbed target {target!r}"
            )
        payload = json.loads(request.data.decode("utf-8"))
        self.calls.append((operation, payload))
        queued = self.refusals.get(operation) or []
        if queued:
            raise _error(queued.pop(0))
        return _Response(getattr(self, f"_{operation.lower()}")(payload))

    def _initiateauth(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        email = (payload.get("AuthParameters") or {}).get("USERNAME", "")
        session = self._next_id("session-%d")
        self.sessions[session] = {"email": email, "used": False, "wrong": 0}
        self._sub_for(email)
        return {
            "ChallengeName": "EMAIL_OTP",
            "AvailableChallenges": ["EMAIL_OTP"],
            "ChallengeParameters": {
                "CODE_DELIVERY_DELIVERY_MEDIUM": "EMAIL",
                "CODE_DELIVERY_DESTINATION": "s***@s***",
            },
            "Session": session,
        }

    def _respondtoauthchallenge(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        session = payload.get("Session", "").replace("+", "-").replace("/", "_")
        state = self.sessions.get(session)
        if state is None or state["used"]:
            raise _error(
                "NotAuthorizedException",
                "Invalid session for the user, session can only be used once.",
            )
        answers = payload.get("ChallengeResponses") or {}
        if answers.get("EMAIL_OTP_CODE") != self.code:
            state["wrong"] += 1
            if state["wrong"] > 5:
                raise _error("NotAuthorizedException", "User temporarily locked")
            raise _error("CodeMismatchException", "Invalid code")
        state["used"] = True
        email = state["email"]
        access = self._next_id("cognito-access-%d")
        refresh = self._next_id("cognito-refresh-%d")
        self.access_tokens[access] = email
        self.refresh_tokens[refresh] = email
        return {
            "AuthenticationResult": {
                "AccessToken": access,
                "IdToken": self._next_id("cognito-id-%d"),
                "RefreshToken": refresh,
                "TokenType": "Bearer",
                "ExpiresIn": 300,
            }
        }

    def _getuser(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        email = self.access_tokens.get(payload.get("AccessToken", ""))
        if email is None:
            raise _error("NotAuthorizedException", "Invalid Access Token")
        username = self.username_override or self._sub_for(email)
        attributes = [{"Name": "sub", "Value": self._sub_for(email)}]
        address = email if self.email_override is None else self.email_override
        if address:
            attributes.append({"Name": "email", "Value": address})
        attributes.append({"Name": "email_verified", "Value": "true"})
        return {"Username": username, "UserAttributes": attributes}

    def _revoketoken(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        token = payload.get("Token", "")
        if token not in self.refresh_tokens:
            raise _error("NotAuthorizedException", "Invalid Refresh Token")
        self.revoked.append(token)
        self.refresh_tokens.pop(token, None)
        return {}
