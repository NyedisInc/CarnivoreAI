
from __future__ import annotations

import io
import json
import os
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("DEFAULT_WORKING_DIR", "/tmp")
os.environ.setdefault("LOG_DIRECTORY", "/tmp")
os.environ.setdefault("TOTP_SECRET", "testsecretnotreal")
os.environ.setdefault("JWT_SECRET", "testjwtnotreal")

# ruff: noqa: E402
from src.config import ProvidersConfig
from src.core.local_models import (
    LOCAL_NOT_CONFIGURED,
    LOCAL_REACHABLE,
    LOCAL_UNREACHABLE,
    fetch_local_models,
    is_embedding_model,
    to_payload,
)


class _Resp(io.BytesIO):

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False


def _opener(body: bytes):
    def _open(url, timeout=None):
        return _Resp(body)
    return _open


def _raising(exc):
    def _open(url, timeout=None):
        raise exc
    return _open


def _models(*ids):
    return json.dumps({"data": [{"id": i} for i in ids]}).encode()




def test_an_unset_address_is_NOT_CONFIGURED_not_unreachable():
    r = fetch_local_models("")
    assert r.state == LOCAL_NOT_CONFIGURED
    assert r.reachable is False
    assert "config.json" in (r.detail or "")


def test_a_refused_connection_is_UNREACHABLE():
    r = fetch_local_models("x:1", opener=_raising(urllib.error.URLError("refused")))
    assert r.state == LOCAL_UNREACHABLE
    assert r.models == []
    assert r.host == "x:1"


def test_a_good_answer_is_REACHABLE_with_models():
    r = fetch_local_models("x:1", opener=_opener(_models("qwen/qwen3-8b", "llama-3")))
    assert r.state == LOCAL_REACHABLE
    assert r.reachable is True
    assert r.models == ["qwen/qwen3-8b", "llama-3"]


def test_reachable_is_false_for_BOTH_non_ok_states():
    assert fetch_local_models("").reachable is False
    assert fetch_local_models(
        "x:1", opener=_raising(OSError("nope"))
    ).reachable is False




@pytest.mark.parametrize("exc", [
    urllib.error.URLError("dns"),
    OSError("socket"),
    TimeoutError("slow"),
    ValueError("weird url"),
])
def test_every_transport_failure_becomes_a_state(exc):
    r = fetch_local_models("x:1", opener=_raising(exc))
    assert r.state == LOCAL_UNREACHABLE


def test_a_non_json_body_is_unreachable_not_a_crash():
    r = fetch_local_models("x:1", opener=_opener(b"<html>nope</html>"))
    assert r.state == LOCAL_UNREACHABLE
    assert "not JSON" in (r.detail or "")


def test_a_json_body_of_the_wrong_shape_is_unreachable():
    r = fetch_local_models("x:1", opener=_opener(b'{"object":"list"}'))
    assert r.state == LOCAL_UNREACHABLE
    assert "OpenAI-shaped" in (r.detail or "")


def test_a_genuinely_empty_list_is_REACHABLE():
    r = fetch_local_models("x:1", opener=_opener(_models()))
    assert r.state == LOCAL_REACHABLE
    assert r.models == []




def test_an_oversized_body_is_refused_rather_than_parsed():
    r = fetch_local_models("x:1", opener=_opener(b"x" * 4096), max_bytes=1024)
    assert r.state == LOCAL_UNREACHABLE
    assert "larger than" in (r.detail or "")


def test_a_body_exactly_at_the_cap_is_still_parsed():
    body = _models("m")
    r = fetch_local_models("x:1", opener=_opener(body), max_bytes=len(body))
    assert r.state == LOCAL_REACHABLE


def test_the_deadline_is_passed_to_the_opener():
    seen = {}

    def _open(url, timeout=None):
        seen["timeout"] = timeout
        seen["url"] = url
        return _Resp(_models("m"))

    fetch_local_models("h:1", deadline=2.5, opener=_open)
    assert seen["timeout"] == 2.5
    assert seen["url"] == "http://h:1/v1/models"




@pytest.mark.parametrize("mid", [
    "text-embedding-nomic-embed-text-v1.5", "bge-large-en", "gte-small",
    "e5-mistral-7b", "some-EMBEDDING-model",
])
def test_embedders_are_filtered_out(mid):
    assert is_embedding_model(mid)
    r = fetch_local_models("x:1", opener=_opener(_models(mid, "qwen3-8b")))
    assert r.models == ["qwen3-8b"]


def test_a_chat_model_is_not_mistaken_for_an_embedder():
    assert not is_embedding_model("qwen/qwen3-8b")
    assert not is_embedding_model("llama-3.1-8b-instruct")




@pytest.mark.parametrize("good", ["10.0.1.5:1234", "localhost:1234", "[::1]:1234"])
def test_a_valid_host_port_survives(good):
    assert ProvidersConfig(local_host=good).local_host == good


@pytest.mark.parametrize("bad", [
    "http://x:1234", "x:1234/path", "x", "x:0", "x:99999", "::1:1234",
    "x:1234;rm -rf /", "x:1234 && id", "user@x:1234", "x:1234?q=1",
    "`id`:1234", "$(id):1234",
])
def test_a_hostile_or_malformed_host_drops_to_NOT_CONFIGURED(bad):
    assert ProvidersConfig(local_host=bad).local_host == ""


def test_the_default_is_empty_rather_than_a_guessed_address():
    assert ProvidersConfig().local_host == ""




def test_the_payload_carries_state_and_the_boolean():
    body = to_payload(fetch_local_models("x:1", opener=_opener(_models("m"))))
    assert body["state"] == LOCAL_REACHABLE
    assert body["reachable"] is True
    assert body["models"] == ["m"]
    assert body["host"] == "x:1"




def test_the_cldl_base_url_has_no_v1_suffix():
    from src.core.agent_wrappers import EXAMPLE_WRAPPERS

    cldl = [w for w in EXAMPLE_WRAPPERS if w["id"] == "cldl"][0]
    assert 'ANTHROPIC_BASE_URL="http://${host}"' in cldl["script"]
    assert "/v1\"" not in cldl["script"], (
        "the base URL carries a /v1 suffix again; the SDK adds its own"
    )


def test_the_cldl_wrapper_refuses_rather_than_guesses():
    from src.core.agent_wrappers import EXAMPLE_WRAPPERS

    cldl = [w for w in EXAMPLE_WRAPPERS if w["id"] == "cldl"][0]
    assert "${CLDL_HOST:?" in cldl["script"]
    assert "${1:?" in cldl["script"]


def test_the_cldl_wrapper_accepts_a_model():
    from src.core.agent_wrappers import EXAMPLE_WRAPPERS

    cldl = [w for w in EXAMPLE_WRAPPERS if w["id"] == "cldl"][0]
    assert cldl["accepts_model"] is True
    assert cldl["family"] == "local"
