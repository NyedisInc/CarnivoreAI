
import json
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace

import pyotp
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from structlog.testing import capture_logs

os.environ.setdefault("DEFAULT_WORKING_DIR", tempfile.mkdtemp(prefix="cc_enroll_wd_"))
os.environ.setdefault("LOG_DIRECTORY", tempfile.mkdtemp(prefix="cc_enroll_logs_"))
os.environ.setdefault("TOTP_SECRET", "JBSWY3DPEHPK3PXP")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-not-a-real-one-32b")

import src.api.auth as auth_mod  # noqa: E402
import src.api.enrollment_routes as enrollment_routes  # noqa: E402
import src.api.setup_routes as setup_routes_module  # noqa: E402
from src.core.owner_identity.otpauth import build_otpauth_uri, sanitize_account  # noqa: E402
from src.core.phone_link.gate import STRIPPED_HEADERS, is_denied  # noqa: E402
from src.config import settings  # noqa: E402

KNOWN = "JBSWY3DPEHPK3PXP"
OTHER = "KRSXG5CTMVRXEZLU"
PORT = settings.port


class Shim:

    def __init__(self, app, updates=None, extra_headers=None):
        self.app, self.updates, self.extra = app, updates or {}, extra_headers or []

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope = dict(scope, **self.updates)
            scope["headers"] = list(scope["headers"]) + self.extra
        await self.app(scope, receive, send)


@pytest.fixture(autouse=True)
def reset_limiter():
    auth_mod.limiter.reset()
    yield
    auth_mod.limiter.reset()


@pytest.fixture()
def env(tmp_path, monkeypatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"agents": {}}))
    monkeypatch.setattr(settings, "auth_config_file", str(cfg))
    monkeypatch.setattr(settings, "totp_secret", KNOWN)
    monkeypatch.setattr(settings, "jwt_secret", "test-jwt-secret-not-a-real-one-32b")
    settings.drop_auth_config_cache()
    for name in ("CARNIVORE_BOUND_HOST", "CLOUDECODE_BOUND_HOST", "CARNIVORE_ALLOW_QR_REPAIR",
                 "CLOUDE_ALLOW_QR_REPAIR", "CLOUDECODE_ALLOW_QR_REPAIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("CLOUDE_BOUND_HOST", "127.0.0.1")
    monkeypatch.setattr(enrollment_routes, "env_file_path", lambda: tmp_path / "absent.env")
    monkeypatch.setattr(enrollment_routes, "computer_display_name", lambda: "Test Mac")
    state = tmp_path / "state"
    state.mkdir()
    monkeypatch.setattr(setup_routes_module, "_state_dir", lambda: state)

    app = FastAPI()
    app.state.limiter = auth_mod.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.include_router(enrollment_routes.router, prefix="/api/v1")
    app.include_router(setup_routes_module.router, prefix="/api/v1")

    class Env:
        sentinel = tmp_path / ".totp_paired"
        tmp = tmp_path

        @staticmethod
        def client(client=("127.0.0.1", 50000), updates=None, extra_headers=None):
            return TestClient(Shim(app, updates, extra_headers),
                              base_url=f"http://127.0.0.1:{PORT}", client=client)

    yield Env()
    settings.drop_auth_config_cache()


def enroll(env, headers=None, **kw):
    return env.client(**kw).get("/api/v1/auth/enrollment", headers=headers or {})


def refused(resp, status=403, reason="enrollment_local_only"):
    assert resp.status_code == status, resp.text
    assert resp.json()["detail"]["reason"] == reason
    assert KNOWN not in resp.text and OTHER not in resp.text and "otpauth" not in resp.text



def test_p1_unpaired_loopback_serves_the_code(env):
    resp = enroll(env)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["secret"] == KNOWN and body["issuer"] == "Carnivore" and body["account"] == "Test Mac"
    assert body["otpauth_uri"].startswith("otpauth://totp/Carnivore:Test%20Mac?")
    assert body["qr_image"].startswith("data:image/svg+xml;base64,")
    assert "no-store" in resp.headers["cache-control"]
    assert "X-RateLimit-Limit" in resp.headers or "x-ratelimit-limit" in resp.headers
    status = env.client().get("/api/v1/auth/enrollment/status").json()
    assert status == {"paired": False, "local": True, "joined": False, "join_pending": False}


def test_p2_localhost_and_ipv6_hosts(env):
    assert enroll(env, {"host": f"localhost:{PORT}"}).status_code == 200
    assert enroll(env, {"host": f"[::1]:{PORT}"}, client=("::1", 50000)).status_code == 200


@pytest.mark.parametrize("hdrs", [
    {"Origin": f"http://127.0.0.1:{PORT}", "Sec-Fetch-Site": "same-origin"},
    {"Sec-Fetch-Site": "none"},
])
def test_p3_same_origin_browser_headers(env, hdrs):
    assert enroll(env, hdrs).status_code == 200


def test_p4_hatch_open_serves_a_paired_install_with_a_warning(env, monkeypatch):
    env.sentinel.touch()
    monkeypatch.setenv("CARNIVORE_ALLOW_QR_REPAIR", "1")
    with capture_logs() as logs:
        assert enroll(env).status_code == 200
    assert any(e["event"] == "enrollment_repair_hatch_served" and e["log_level"] == "warning" for e in logs)


@pytest.mark.parametrize("bound,expect", [(None, "unrecorded"), ("0.0.0.0", "0.0.0.0")])
def test_p5_unlocked_bind_warns(env, monkeypatch, bound, expect):
    monkeypatch.delenv("CLOUDE_BOUND_HOST")
    if bound:
        monkeypatch.setenv("CLOUDE_BOUND_HOST", bound)
    with capture_logs() as logs:
        assert enroll(env).status_code == 200
    events = [e for e in logs if e["event"] == "enrollment_served_unlocked_bind"]
    assert len(events) == 1 and events[0]["bound_host"] == expect


def test_p5_locked_bind_does_not_warn(env):
    with capture_logs() as logs:
        assert enroll(env).status_code == 200
    assert not [e for e in logs if e["event"] == "enrollment_served_unlocked_bind"]



def test_r1_lan_client_on_an_unlocked_bind(env, monkeypatch):
    monkeypatch.setenv("CLOUDE_BOUND_HOST", "0.0.0.0")
    refused(enroll(env, client=("198.51.100.18", 50000)))


@pytest.mark.parametrize("header", [
    "X-Forwarded-For", "Forwarded", "X-Real-IP", "X-Forwarded-Proto", "Via", "Tailscale-User-Login",
])
def test_r2_to_r7_forwarding_headers(env, header):
    refused(enroll(env, {header: "1.2.3.4"}))


@pytest.mark.parametrize("host", [
    f"198.51.100.18:{PORT}", f"127.0.0.1:{PORT + 1}", "127.0.0.1",
    "example.net#@localhost", "example.net?.localhost",
])
def test_r8_to_r12_bad_host(env, host):
    refused(enroll(env, {"host": host}))


def test_r13_two_host_headers(env):
    refused(env.client(extra_headers=[(b"host", f"127.0.0.1:{PORT}".encode())]).get("/api/v1/auth/enrollment"))


def test_r14_other_listener_port(env):
    refused(env.client(updates={"server": ("127.0.0.1", PORT + 7)}).get("/api/v1/auth/enrollment"))


@pytest.mark.parametrize("tag", ["via_link", "via_peer_link"])
def test_r15_r16_link_tags(env, tag):
    refused(env.client(updates={tag: True}).get("/api/v1/auth/enrollment"))


@pytest.mark.parametrize("origin", [
    "http://evil.example", "null", f"http://test-name.local:{PORT}", f"https://127.0.0.1:{PORT}",
])
def test_r17_to_r20_bad_origin(env, origin):
    refused(enroll(env, {"Origin": origin}))


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_r21_r22_bad_sec_fetch_site(env, site):
    refused(enroll(env, {"Sec-Fetch-Site": site}))


def test_r23_authorization_header(env):
    refused(enroll(env, {"Authorization": "Bearer x"}))



def test_s1_already_paired(env):
    env.sentinel.touch()
    refused(enroll(env), 409, "already_paired")


def test_s2_sentinel_check_raises_oserror(env, monkeypatch):
    real = Path.exists

    def boom(self):
        if self.name == ".totp_paired":
            raise OSError("denied")
        return real(self)

    monkeypatch.setattr(Path, "exists", boom)
    refused(enroll(env), 503, "setup_undetermined")
    assert env.client().get("/api/v1/auth/enrollment/status").json()["paired"] is None


@pytest.mark.parametrize("empty", ["", "   "])
def test_s3_no_totp_secret_in_memory(env, monkeypatch, empty):
    monkeypatch.setattr(settings, "totp_secret", empty)
    settings.drop_auth_config_cache()
    refused(enroll(env), 503, "totp_not_configured")


def test_s3_control_missing_jwt_secret_is_config_unreadable(env, monkeypatch):
    monkeypatch.setattr(settings, "jwt_secret", "")
    settings.drop_auth_config_cache()
    refused(enroll(env), 503, "config_unreadable")


def test_s4_hatch_never_skips_the_transport(env, monkeypatch):
    env.sentinel.touch()
    monkeypatch.setenv("CARNIVORE_ALLOW_QR_REPAIR", "1")
    refused(enroll(env, {"X-Forwarded-For": "9.9.9.9"}))


def test_s5_rotate_reopens_the_route(env):
    env.sentinel.touch()
    assert env.client().get("/api/v1/auth/enrollment/status").json()["paired"] is True
    env.sentinel.unlink()
    assert env.client().get("/api/v1/auth/enrollment/status").json()["paired"] is False
    assert enroll(env).status_code == 200


def test_s6_pending_rotate(env, monkeypatch):
    monkeypatch.delenv("TOTP_SECRET", raising=False)
    dotenv = env.tmp / ".env"
    monkeypatch.setattr(enrollment_routes, "env_file_path", lambda: dotenv)
    dotenv.write_text(f"TOTP_SECRET={OTHER}\n")
    refused(enroll(env), 409, "restart_pending")
    dotenv.write_text(f"TOTP_SECRET={KNOWN}\n")
    assert enroll(env).status_code == 200
    auth_mod.limiter.reset()
    dotenv.write_text(f"TOTP_SECRET={OTHER}\n")
    monkeypatch.setenv("TOTP_SECRET", KNOWN)
    assert enroll(env).status_code == 200


def test_s7_config_unreadable_logs_the_type_not_the_path(env, monkeypatch):
    def boom(self):
        raise FileNotFoundError("/secret/path/config.json")

    monkeypatch.setattr(type(settings), "load_auth_config", boom)
    with capture_logs() as logs:
        refused(enroll(env), 503, "config_unreadable")
    ev = [e for e in logs if e["event"] == "enrollment_refused" and e.get("reason") == "config_unreadable"]
    assert ev and ev[0]["error_type"] == "FileNotFoundError"
    assert "/secret/path" not in json.dumps(ev, default=str)


def test_s8_qr_failure(env, monkeypatch):
    def boom(uri):
        raise ValueError("too big")

    monkeypatch.setattr(enrollment_routes, "_render_qr", boom)
    refused(enroll(env), 500, "qr_generation_failed")


def test_s10_the_limit_is_real(env):
    client = env.client()
    codes = [client.get("/api/v1/auth/enrollment").status_code for _ in range(11)]
    assert codes == [200] * 10 + [429]


def test_s10b_next_test_starts_clean(env):
    assert enroll(env).status_code == 200


@pytest.mark.parametrize("hatch", [False, True])
def test_s11_tombstone(env, monkeypatch, hatch):
    if hatch:
        env.sentinel.touch()
        monkeypatch.setenv("CARNIVORE_ALLOW_QR_REPAIR", "1")
    resp = env.client().get("/api/v1/auth/qr")
    assert resp.status_code == 403 and resp.json()["detail"]["reason"] == "qr_moved"
    assert "no-store" in resp.headers["cache-control"]
    assert KNOWN not in resp.text and "otpauth" not in resp.text and "secret" not in resp.text



def test_w1_wizard_state_is_local_only_while_incomplete(env):
    assert env.client().get("/api/v1/setup/state").status_code == 200
    resp = env.client(client=("192.0.2.13", 50000)).get("/api/v1/setup/state")
    assert resp.status_code == 403 and resp.json()["detail"]["reason"] == "setup_local_only"


def test_w2_wizard_apply_refuses_a_foreign_origin(env):
    resp = env.client().post("/api/v1/setup/apply", json={"decisions": []},
                             headers={"Origin": "http://evil.example"})
    assert resp.status_code == 403


def test_w3_setup_finish_is_gone(env):
    assert env.client().post("/api/v1/setup/finish").status_code in (404, 405)



def test_l1_phone_link_denies_enrollment_and_strips_forwarding():
    assert is_denied("/api/v1/auth/enrollment") and is_denied("/api/v1/auth/enrollment/status")
    assert is_denied("/API/v1/Auth/Enrollment")
    assert not is_denied("/api/v1/auth/enrollmentx")
    assert all(isinstance(h, bytes) and h == h.lower() for h in STRIPPED_HEADERS)
    assert b"via" in STRIPPED_HEADERS and b"cf-connecting-ip" in STRIPPED_HEADERS


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "otpauth_uri_cases.json"


@pytest.mark.parametrize("row", json.loads(FIXTURE.read_text()))
def test_l2_label_rule_matches_the_shared_fixture(row):
    assert sanitize_account(row["computer_name"]) == row["account"]
    assert build_otpauth_uri(row["secret"], row["computer_name"]) == row["uri"]


def test_l3_pyotp_round_trips_the_uri():
    totp = pyotp.parse_uri(build_otpauth_uri(KNOWN, "Alex's (Mac)"))
    assert totp.secret == KNOWN and totp.issuer == "Carnivore"
