
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple

import pytest

from src.core.cli_command import service as cli_service
from src.plugins.host import netguard, sidecar_registry, sidecar_spec
from src.plugins.host.egress_log import EgressLog
from src.plugins.host.fetch_proxy import FetchRefused, PluginFetch, RateLimiter
from src.plugins.host.fetch_transport import RawResponse
from src.plugins.host.secret_store import SecretStore
from src.plugins.host.plugin_manifest import load_sidecar_manifest
from src.plugins.host.sidecar_services import _map_fetch_error
from src.plugins.runtime import guards, sandbox
from src.plugins.runtime.dispatch import HostDispatcher, HostServices, PluginContext
from src.plugins.runtime.owner_tokens import OwnerTokens
from src.plugins.runtime.supervisor import Supervisor


TEST_SECRET_VALUE = "testsecretnotreal"


def _can_run_darwin_sandbox() -> bool:
    if sys.platform != "darwin" or not os.path.exists("/usr/bin/sandbox-exec"):
        return False
    try:
        sandbox.find_interpreter()
        return True
    except sandbox.SandboxUnavailable:
        return False


DARWIN_SANDBOX = _can_run_darwin_sandbox()


def _has_runtime(finder: Any) -> bool:
    try:
        finder()
        return True
    except sandbox.SandboxUnavailable:
        return False


class _FakeKeychain:
    def __init__(self) -> None:
        self.items: Dict[Tuple[str, str], str] = {}

    def read(self, service: str, account: str) -> str | None:
        return self.items.get((service, account))

    def write(self, service: str, account: str, secret: str) -> None:
        self.items[(service, account)] = secret

    def delete(self, service: str, account: str) -> bool:
        return self.items.pop((service, account), None) is not None


class _MockTransport:
    def __init__(self, handler: Any) -> None:
        self._handler = handler

    def send(self, **kw: Any) -> RawResponse:
        return self._handler(SimpleNamespace(**kw))


def _build_http_fetch_service(
    manifest: Any,
    install_key: str,
    grants: frozenset[str],
    state_dir: Path,
    secrets: SecretStore,
    egress: EgressLog,
    seen_requests: List[Dict[str, Any]],
) -> Any:
    def _transport_handler(req: SimpleNamespace) -> RawResponse:
        seen_requests.append(
            {
                "host": req.host,
                "method": req.method,
                "target": req.target,
                "headers": {k.lower(): v for k, v in req.headers},
                "body": req.body.decode("utf-8", errors="replace") if req.body else "",
            }
        )
        return RawResponse(
            status=200,
            headers=[
                ("content-type", "application/json"),
                ("authorization", f"Bearer {TEST_SECRET_VALUE}"),
                ("x-echo-secret", f"Bearer {TEST_SECRET_VALUE}"),
                ("x-upstream", "ok"),
            ],
            body=json.dumps({"echo": TEST_SECRET_VALUE, "ok": True}).encode("utf-8"),
        )

    fetcher = PluginFetch(
        manifest,
        install_key,
        lambda: tuple(grants),
        secrets,
        egress,
        RateLimiter(per_minute=60),
        peers=lambda: netguard.Peers(frozenset()),
        resolver=lambda _host, _port: ["93.184.216.34"],
        transport=_MockTransport(_transport_handler),
        is_own=lambda _ip: False,
    )

    async def _http_fetch(_ctx: PluginContext, params: Dict[str, Any]) -> Dict[str, Any]:
        raw_body = params.get("body")
        if raw_body is None:
            body = None
        elif isinstance(raw_body, str):
            body = raw_body.encode("utf-8")
        elif isinstance(raw_body, (bytes, bytearray)):
            body = bytes(raw_body)
        else:
            raise guards.Refused("invalid_params", "body")
        try:
            resp = await fetcher.fetch(
                params.get("method", "GET"),
                params.get("url", ""),
                headers=params.get("headers"),
                body=body,
            )
        except FetchRefused as exc:
            raise _map_fetch_error(exc) from exc
        return {
            "status": resp.status,
            "headers": dict(resp.headers),
            "body": resp.body.decode("utf-8", errors="replace"),
            "truncated": resp.truncated,
        }

    return _http_fetch


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
@pytest.mark.parametrize("mode", ["rpc", "oneshot"])
async def test_real_sandbox_exec_bash_rpc_and_oneshot_carnivore_bin_fetch_secret_and_denial(
    tmp_path: Path,
    mode: str,
) -> None:
    plugin_id = f"bashe2e{mode}"
    code_dir = tmp_path / "code" / plugin_id
    code_dir.mkdir(parents=True)
    state_dir = tmp_path / "state"
    cli_service.write_shim(state_dir)

    body_steps = """
set +e
SESS=$("$CARNIVORE_BIN" sessions list --json)
PROJ=$("$CARNIVORE_BIN" projects list)
"$CARNIVORE_BIN" storage put k1 '{"ok":true}' >/dev/null
SVC=$("$CARNIVORE_BIN" service call math.v1 add '{"a":2,"b":5}')
EV=$("$CARNIVORE_BIN" event emit demo.ping '{"ok":true}')
FETCH=$("$CARNIVORE_BIN" fetch https://api.example.com/v1/echo -X POST -H 'Authorization: Bearer $SECRET:api_token' --json '{"ping":1}')

DENY_TOAST_ERR=$("$CARNIVORE_BIN" notify toast "Denied" 2>&1 >/dev/null)
DENY_TOAST_RC=$?
DENY_HOST_ERR=$("$CARNIVORE_BIN" fetch https://unlisted.evil.example/steal 2>&1 >/dev/null)
DENY_HOST_RC=$?
AFTER_DENY=$("$CARNIVORE_BIN" storage get k1)
set -e

RESULT=$(CARN_SESS="$SESS" CARN_PROJ="$PROJ" CARN_SVC="$SVC" CARN_EV="$EV" CARN_FETCH="$FETCH" \\
  CARN_TOAST_ERR="$DENY_TOAST_ERR" CARN_TOAST_RC="$DENY_TOAST_RC" \\
  CARN_HOST_ERR="$DENY_HOST_ERR" CARN_HOST_RC="$DENY_HOST_RC" \\
  CARN_AFTER="$AFTER_DENY" "$CARNIVORE_SOCK_PYTHON" -c '
import json, os
print(json.dumps({
  "sessions": json.loads(os.environ["CARN_SESS"]),
  "projects": json.loads(os.environ["CARN_PROJ"]),
  "service": json.loads(os.environ["CARN_SVC"]),
  "event": json.loads(os.environ["CARN_EV"]),
  "fetch": json.loads(os.environ["CARN_FETCH"]),
  "deny_toast_rc": int(os.environ["CARN_TOAST_RC"]),
  "deny_toast_err": os.environ["CARN_TOAST_ERR"],
  "deny_host_rc": int(os.environ["CARN_HOST_RC"]),
  "deny_host_err": os.environ["CARN_HOST_ERR"],
  "after_deny": json.loads(os.environ["CARN_AFTER"]),
}, separators=(",", ":")))
')
"""

    if mode == "rpc":
        (code_dir / "main.sh").write_text(
            f"""#!/bin/bash
while IFS= read -r line; do
  id="${{line##*\\"id\\":}}"
  id="${{id%%,*}}"
  id="${{id%%\\}}*}}"
  id="${{id//[!0-9]/}}"
  if [[ "$line" == *'"initialize"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"api_version":1,"capabilities":{{"tools":true}},"subscriptions":[]}}}}\\n' "$id"
  elif [[ "$line" == *'"tools/list"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"tools":[{{"name":"run_e2e","description":"Run E2E","gate":"read","inputSchema":{{"type":"object"}}}}]}}}}\\n' "$id"
  elif [[ "$line" == *'"tools/call"'* ]]; then
{body_steps}
    printf '{{"jsonrpc":"2.0","id":%s,"result":%s}}\\n' "$id" "$RESULT"
  elif [[ "$line" == *'"shutdown"'* ]]; then
    printf '{{"jsonrpc":"2.0","id":%s,"result":{{"ok":true}}}}\\n' "$id"
    exit 0
  fi
done
""",
            encoding="utf-8",
        )
    else:
        (code_dir / "main.sh").write_text(
            f"""#!/bin/bash
IFS= read -r _req || true
{body_steps}
printf '%s\\n' "$RESULT"
""",
            encoding="utf-8",
        )
    (code_dir / "main.sh").chmod(0o755)

    (code_dir / "carnivore.toml").write_text(
        f"""schema = 2
id = "{plugin_id}"
name = "Bash E2E {mode}"
version = "1.0.0"
kind = "plugin"
description = "Bash E2E secret + denial fixture"
author = "Tester"

[run]
cmd = ["bash", "main.sh"]
mode = "{mode}"

[permissions]
read = ["sessions"]
services = ["math.v1"]
events = ["demo.ping"]
network = [{{ host = "api.example.com", methods = ["POST"], paths = ["/v1/"] }}]
secrets = ["api_token"]

[services]
consumes = ["math.v1"]

[events]
emit = ["demo.ping"]

[mcp]
[[mcp.tools]]
name = "run_e2e"
description = "Run E2E"
gate = "read"
inputSchema = {{ type = "object" }}
""",
        encoding="utf-8",
    )

    install_key = f"inst-bash-{mode}"
    data_dir = state_dir / "cplugs" / install_key
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    manifest = load_sidecar_manifest(code_dir, plugin_id, allow_local=True)
    defn = sidecar_registry.SidecarDefinition(
        manifest=manifest,
        item_id=f"local/{plugin_id}",
        install_key=install_key,
        code_root=code_dir,
        folder=data_dir,
    )
    grants = frozenset(manifest.permissions) | frozenset({"services:math.v1", "events:demo.ping"})
    spec = sidecar_spec.build_spec(defn, grants, {}, consented=True, consent_owed=False)

    secrets = SecretStore(state_dir, keychain=_FakeKeychain())
    secrets.set(install_key, manifest, "api_token", TEST_SECRET_VALUE)
    egress = EgressLog(state_dir)
    seen_requests: List[Dict[str, Any]] = []
    service_calls: List[Tuple[str, str, str, Any]] = []
    emitted_events: List[Tuple[str, str, Any]] = []

    async def _list_sessions() -> List[Dict[str, Any]]:
        return [{"session": {"id": "ses-e2e"}, "label": "e2e"}]

    async def _list_projects() -> List[Dict[str, Any]]:
        return [{"id": 7, "name": "core"}]

    async def _svc_call(ctx: PluginContext, service: str, method: str, args: Any) -> Dict[str, Any]:
        service_calls.append((ctx.plugin_id, service, method, args))
        return {"service": service, "method": method, "sum": args["a"] + args["b"]}

    async def _events_emit(ctx: PluginContext, event: str, payload: Any) -> Dict[str, Any]:
        emitted_events.append((ctx.plugin_id, event, payload))
        return {"event": event, "emitted": True}

    http_fetch = _build_http_fetch_service(manifest, install_key, grants, state_dir, secrets, egress, seen_requests)
    disp = HostDispatcher(
        HostServices(
            activity=lambda _r: None,
            list_sessions=_list_sessions,
            list_projects=_list_projects,
            service_call=_svc_call,
            events_emit=_events_emit,
            http_fetch=http_fetch,
        ),
        OwnerTokens(b"e" * 32),
    )
    sup = Supervisor(
        state_dir,
        "1.0.0",
        disp,
        lambda _pid, _k, _why: None,
        lambda _pid: {},
        lambda _r: None,
        index={"expires_at": "2999-01-01T00:00:00Z"},
    )
    try:
        assert await sup.enable(spec) == "running"
        proc = await sup.ensure(plugin_id)
        assert proc is not None
        raw_res = await proc.request("tools/call", {"name": "run_e2e", "arguments": {}})
        res = json.loads(raw_res["content"][0]["text"]) if "content" in raw_res else raw_res

        assert res["sessions"] == {"sessions": [{"id": "ses-e2e", "label": "e2e"}]}
        assert res["projects"] == {"projects": [{"id": 7, "name": "core"}]}
        assert res["service"] == {"service": "math.v1", "method": "add", "sum": 7}
        assert res["event"] == {"event": "demo.ping", "emitted": True}
        assert service_calls == [(plugin_id, "math.v1", "add", {"a": 2, "b": 5})]
        assert emitted_events == [(plugin_id, "demo.ping", {"ok": True})]

        assert len(seen_requests) == 1
        upstream = seen_requests[0]
        assert upstream["host"] == "api.example.com"
        assert upstream["method"] == "POST"
        assert upstream["target"] == "/v1/echo"
        assert upstream["headers"]["authorization"] == f"Bearer {TEST_SECRET_VALUE}"
        assert json.loads(upstream["body"]) == {"ping": 1}

        fetch_res = res["fetch"]
        assert fetch_res["status"] == 200
        assert "[redacted]" in fetch_res["body"]
        assert TEST_SECRET_VALUE not in fetch_res["body"]
        assert "authorization" not in fetch_res["headers"]
        assert "x-echo-secret" not in fetch_res["headers"]
        assert fetch_res["headers"].get("x-upstream") == "ok"
        assert TEST_SECRET_VALUE not in json.dumps(fetch_res["headers"])
        assert any(row.get("outcome") == "credential_echo" for row in egress.recent(install_key))

        assert res["deny_toast_rc"] != 0
        assert "-32002:not_granted" in res["deny_toast_err"]
        assert res["deny_host_rc"] != 0
        assert "-32002:not_granted" in res["deny_host_err"]
        assert res["after_deny"] == {"value": {"ok": True}}
        assert disp.storage(spec.ctx).get("k1") == {"ok": True}
    finally:
        await sup.shutdown()


@pytest.mark.asyncio
@pytest.mark.skipif(not DARWIN_SANDBOX, reason="needs macOS sandbox-exec and framework Python")
@pytest.mark.parametrize(
    ("runtime_name", "finder", "cmd", "mode"),
    [
        ("node", sandbox._find_node, ["node", "main.mjs"], "rpc"),
        ("node", sandbox._find_node, ["node", "main.mjs"], "oneshot"),
        ("bun", sandbox._find_bun, ["bun", "main.ts"], "rpc"),
        ("bun", sandbox._find_bun, ["bun", "main.ts"], "oneshot"),
    ],
)
async def test_real_sandbox_exec_ts_sdk_http_fetch_secret_and_permission_denial(
    tmp_path: Path,
    runtime_name: str,
    finder: Any,
    cmd: List[str],
    mode: str,
) -> None:
    if not _has_runtime(finder):
        pytest.skip(f"{runtime_name} runtime not installed")

    plugin_id = f"tssdksec{runtime_name}{mode}"
    code_dir = tmp_path / "code"
    code_dir.mkdir(parents=True)
    ext = "ts" if cmd[-1].endswith(".ts") else "mjs"
    (code_dir / "carnivore.toml").write_text(
        f"""schema = 2
id = "{plugin_id}"
name = "TS SDK Secret & Denial"
version = "1.0.0"
kind = "plugin"
description = "TS SDK httpFetch secret + HostError denial inside sandbox-exec"
author = "Tester"

[run]
cmd = {json.dumps(cmd)}
mode = "{mode}"

[permissions]
network = [{{ host = "api.example.com", methods = ["POST"], paths = ["/v1/"] }}]
secrets = ["api_token"]

[[mcp.tools]]
name = "fetch_and_deny"
description = "Fetch and deny"
gate = "read"
inputSchema = {{ type = "object" }}
""",
        encoding="utf-8",
    )
    (code_dir / f"main.{ext}").write_text(
        """import { HostError, Plugin } from "@carnivore/plugin-sdk";

const plugin = new Plugin().tool("fetch_and_deny", "Fetch and deny", async () => {
  const fetchRes = await plugin.host.httpFetch("https://api.example.com/v1/echo", {
    method: "POST",
    headers: { Authorization: "Bearer $SECRET:api_token" },
    json: { ping: 1 },
  });

  let denied = null;
  try {
    await plugin.host.notify.toast("app", "Denied");
  } catch (err) {
    if (err instanceof HostError) {
      denied = { code: err.code, reason: err.reason };
    } else {
      throw err;
    }
  }

  await plugin.host.storage.put("survived", true);
  const survived = await plugin.host.storage.get("survived");
  return { fetch: fetchRes, denied, survived: survived.value };
});

await plugin.serve();
""",
        encoding="utf-8",
    )
    assert not (code_dir / "node_modules").exists()

    state_dir = tmp_path / "state"
    install_key = f"inst-ts-sec-{runtime_name}-{mode}"
    data_dir = state_dir / "cplugs" / install_key
    (data_dir / "files").mkdir(parents=True, exist_ok=True)
    manifest = load_sidecar_manifest(code_dir, plugin_id, allow_local=True)
    defn = sidecar_registry.SidecarDefinition(
        manifest=manifest,
        item_id=f"local/{plugin_id}",
        install_key=install_key,
        code_root=code_dir,
        folder=data_dir,
    )
    grants = frozenset(manifest.permissions)
    spec = sidecar_spec.build_spec(defn, grants, {}, consented=True, consent_owed=False)

    secrets = SecretStore(state_dir, keychain=_FakeKeychain())
    secrets.set(install_key, manifest, "api_token", TEST_SECRET_VALUE)
    egress = EgressLog(state_dir)
    seen_requests: List[Dict[str, Any]] = []
    http_fetch = _build_http_fetch_service(manifest, install_key, grants, state_dir, secrets, egress, seen_requests)

    disp = HostDispatcher(HostServices(activity=lambda _r: None, http_fetch=http_fetch), OwnerTokens(b"t" * 32))
    sup = Supervisor(
        state_dir,
        "1.0.0",
        disp,
        lambda _pid, _k, _why: None,
        lambda _pid: {},
        lambda _r: None,
        index={"expires_at": "2999-01-01T00:00:00Z"},
    )
    try:
        assert await sup.enable(spec) == "running"
        proc = sup.process(plugin_id)
        assert proc is not None
        raw = await proc.request("tools/call", {"name": "fetch_and_deny", "arguments": {}})
        parsed = json.loads(raw["content"][0]["text"])

        assert len(seen_requests) == 1
        assert seen_requests[0]["headers"]["authorization"] == f"Bearer {TEST_SECRET_VALUE}"
        assert json.loads(seen_requests[0]["body"]) == {"ping": 1}

        fetch_res = parsed["fetch"]
        assert fetch_res["status"] == 200
        assert "[redacted]" in fetch_res["body"]
        assert TEST_SECRET_VALUE not in fetch_res["body"]
        assert "authorization" not in fetch_res["headers"]
        assert "x-echo-secret" not in fetch_res["headers"]
        assert fetch_res["headers"].get("x-upstream") == "ok"
        assert TEST_SECRET_VALUE not in json.dumps(fetch_res["headers"])
        assert any(row.get("outcome") == "credential_echo" for row in egress.recent(install_key))

        assert parsed["denied"] == {"code": -32002, "reason": "not_granted"}
        assert parsed["survived"] is True
        assert disp.storage(spec.ctx).get("survived") is True
    finally:
        await sup.shutdown()
