
from __future__ import annotations

from fastapi import HTTPException, Request

from src.core.federation import peer_token

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
PEER_FORBIDDEN_CODE = "peer_forbidden"


async def refuse_peer_token_writes(request: Request) -> None:
    if request.method in READ_METHODS:
        return
    header = request.headers.get("authorization", "")
    token = header[7:] if header[:7].lower() == "bearer " else ""
    if token and peer_token.is_peer_token(token):
        raise HTTPException(status_code=403, detail={"code": PEER_FORBIDDEN_CODE,
                                                      "detail": "a paired computer cannot change plugins on this computer"})
