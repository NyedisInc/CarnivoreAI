
import os
import ssl
import urllib.request

import httpx
import pytest

HOST = os.environ.get("TESTSRV_LINK_HOST", "")
ROOT_URL = "https://letsencrypt.org/certs/staging/gen-y/root-ye.pem"

pytestmark = pytest.mark.skipif(not HOST, reason="needs a slot from `scripts/testsrv lease --link`")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    ca = os.environ.get("TESTSRV_LINK_CA")
    if not ca:
        ca = str(tmp_path_factory.mktemp("ca") / "staging-root.pem")
        with urllib.request.urlopen(ROOT_URL, timeout=30) as response, open(ca, "wb") as out:
            out.write(response.read())
    ctx = ssl.create_default_context(cafile=ca)
    ctx.verify_flags &= ~ssl.VERIFY_X509_STRICT
    with httpx.Client(base_url=f"https://{HOST}", verify=ctx, follow_redirects=False, timeout=30) as c:
        yield c


def test_no_cookie_redirects_to_pair_and_pair_is_served(client):
    root = client.get("/")
    assert root.status_code == 302 and root.headers["location"] == "/pair"
    page = client.get("/pair")
    assert page.status_code == 200 and "carnivore pairing" in page.text


def test_mcp_hosts_and_the_owner_api_are_refused_through_the_link(client):
    for method, path in (("POST", "/mcp"), ("GET", "/api/v1/hosts"), ("GET", "/api/v1/federation/hello"),
                         ("POST", "/api/v1/phone-link/pairing-window"), ("GET", "/api/v1/phone-link/devices")):
        assert client.request(method, path).status_code == 403, path


def test_a_wrong_cookie_is_still_unpaired(client):
    resp = client.get("/api/v1/sessions/list", headers={"cookie": "__Host-cc_link=nope"})
    assert resp.status_code == 302 and resp.headers["location"] == "/pair"


def test_a_newline_or_control_byte_in_the_path_is_a_400_never_a_hosts_answer(client):
    for path in ("/api/v1/hosts%0A", "/api/v1/hosts%0D", "/api/v1/hosts%09", "/mcp%0A", "/api/v1/auth/qr%0A"):
        assert client.request("GET", path).status_code == 400, path
    assert client.get("/api/v1/hosts//").status_code == 403
    assert client.get("/API/V1/HOSTS").status_code == 403
