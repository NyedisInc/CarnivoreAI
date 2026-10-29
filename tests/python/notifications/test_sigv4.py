
from __future__ import annotations

from datetime import datetime, timezone

from src.core.notifications.kinds.sigv4 import canonical_request, sign_v4

AK = "AKIDEXAMPLE"
SK = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
NOW = lambda: datetime(2015, 8, 30, 12, 36, 0, tzinfo=timezone.utc)  # noqa: E731
TOKEN = (
    "AQoDYXdzEPT//////////wEXAMPLEtc764bNrC9SAPBSM22wDOk4x4HIZ8j4FZTwdQWLWsKWHGBuFqwAeMicRXmxfpSPfIeoIYRqTflfKD8YUuwthAx7mSEI/"
    "qkPpKPi/kMcGdQrmGdeehM4IC1NtBmUpp2wUE8phUZampKsburEDy0KPkyQDYwT7WZ0wq5VSXDvp75YU9HFvlRd8Tx6q6fE8YQcHNVXAkiY9q6d+xo0rKwT38xVqr7ZD0u0iPPkUL64lIZbqBAz+"
    "scqKmlzm8FDrypNC9Yjc8fPOLn9FX9KSYvKTr4rvx3iSIlTJabIQwj2ICCR/oLxBA=="
)


def _sign(**kw):
    return sign_v4(
        host="example.amazonaws.com", access_key=AK, secret_key=SK,
        region="us-east-1", service="service", clock=NOW, **kw,
    )


def test_get_vanilla():
    out = _sign(method="GET")
    assert out["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date, "
        "Signature=5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"
    )
    assert out["X-Amz-Date"] == "20150830T123600Z"


def test_post_x_www_form_urlencoded():
    out = _sign(
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=b"Param1=value1",
    )
    assert out["Authorization"].endswith(
        "SignedHeaders=content-type;host;x-amz-date, "
        "Signature=ff11897932ad3f4e8b18135d722051e5ac45fc38421b1da7b9d196a0fe09473a"
    )
    creq, _ = canonical_request(
        method="POST", path="/", query="",
        headers={"content-type": "application/x-www-form-urlencoded",
                 "host": "example.amazonaws.com", "x-amz-date": "20150830T123600Z"},
        payload=b"Param1=value1",
    )
    assert creq == (
        "POST\n/\n\ncontent-type:application/x-www-form-urlencoded\n"
        "host:example.amazonaws.com\nx-amz-date:20150830T123600Z\n\n"
        "content-type;host;x-amz-date\n"
        "9095672bbd1f56dfc5b65f3e153adc8731a4a654192329106275f4c7b24d0b6e"
    )


def test_post_sts_header_before_signs_the_token():
    out = _sign(method="POST", session_token=TOKEN)
    assert out["X-Amz-Security-Token"] == TOKEN
    assert out["Authorization"] == (
        "AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/20150830/us-east-1/service/aws4_request, "
        "SignedHeaders=host;x-amz-date;x-amz-security-token, "
        "Signature=85d96828115b5dc0cfc3bd16ad9e210dd772bbebba041836c64533a82be05ead"
    )


def test_wrong_secret_goes_red():
    bad = sign_v4(
        method="GET", host="example.amazonaws.com", access_key=AK, secret_key="nope",
        region="us-east-1", service="service", clock=NOW,
    )
    assert "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31" not in bad["Authorization"]


def test_sns_publish_canonical_layout():
    body = b"Action=Publish&Message=hi&PhoneNumber=%2B15555550100&Version=2010-03-31"
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
    out = sign_v4(
        method="POST", host="sns.us-east-1.amazonaws.com", headers=headers, body=body,
        access_key=AK, secret_key=SK, region="us-east-1", service="sns", clock=NOW,
    )
    signed_headers = {k.lower(): v for k, v in out.items() if k != "Authorization"}
    creq, signed = canonical_request(
        method="POST", path="/", query="", headers=signed_headers, payload=body
    )
    lines = creq.split("\n")
    assert lines[0] == "POST" and lines[1] == "/" and lines[2] == ""
    assert lines[3:6] == [
        "content-type:application/x-www-form-urlencoded; charset=utf-8",
        "host:sns.us-east-1.amazonaws.com",
        "x-amz-date:20150830T123600Z",
    ]
    assert lines[6] == "" and lines[7] == "content-type;host;x-amz-date" == signed
    assert len(lines[8]) == 64
    assert "Credential=AKIDEXAMPLE/20150830/us-east-1/sns/aws4_request" in out["Authorization"]
