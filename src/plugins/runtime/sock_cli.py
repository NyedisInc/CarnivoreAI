
from __future__ import annotations

import base64
import json
import os
import socket
import sys
from typing import Any, Dict, List, Optional, Tuple

MAX_RESPONSE_BYTES = 1024 * 1024 + 4096
DEFAULT_TIMEOUT_S = 15.0
AI_CALL_TIMEOUT_S = 90.0
SESSION_STOP_TIMEOUT_S = 135.0


class SockCliUsageError(ValueError):
    pass


class SockCliRpcError(RuntimeError):
    pass

HELP_TEXT = """usage: carnivore [--timeout SEC] [--json] <command> [args...]

Scoped plugin sandbox commands (talking over $CARNIVORE_PLUGIN_SOCK):
  sessions list | get <ref> | output <ref> [--lines N] | permission-mode <ref>
  sessions message <ref> <line> --owner-token <tok>
  sessions create --project <id> [--prompt TEXT] [--family claude|codex]
  sessions control <ref> <restart|stop|sleep|wake>
  notify [toast] <title> [--ref <ref>]
  notify alert <key> <severity> <title> [<json_params>]
  fetch <url> [-X|--method M] [-H|--header K:V] [-d|--data|--body TEXT] [--json JSON] [--body-stdin]
  storage get <key> | put <key> (<value>|--stdin|-) | delete <key> | list [--prefix P]
  projects list | git <project_id> <status|branch|remote|diff_names> | snapshot <project_id> <turn>
  exports write <folder> <name> (--text TEXT | --bytes-b64 B64 | --stdin)
  ai call <feature> <capability> [<json_input> | --prompt TEXT [--max-tokens N]]
  ledger read
  topic publish <name> [--key KEY]
  ui invalidate [<surface>] | slot-publish <slot> [<json_items> | --items JSON]
  log <level> <event> [<json_fields>]
  process snapshot
  mcp config [--session REF] | links [--session REF]
  flow run <id> [--seed S] [--start F] [--end F] [--refresh]
  flow run-part <token> <index>
  flow feed <id> <topic> [--seed S] [--start F] [--cursor F]
  flow tasks [--query Q] [--limit N]
  service call <service> <method> [<json_args> | --args JSON]
  event[s] emit <event> [<json_payload>]
  call <rpc_method> [<json_params>]
"""


def rpc_call(
    sock_path: str,
    method: str,
    params: Dict[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_S,
) -> Any:
    payload = (
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, separators=(",", ":")).encode("utf-8")
        + b"\n"
    )
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect(sock_path)
        sock.sendall(payload)
        buf = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\n" in buf:
                break
            if len(buf) > MAX_RESPONSE_BYTES:
                raise SockCliRpcError("response_too_large")
    finally:
        sock.close()
    line = bytes(buf).splitlines()[0] if buf else b""
    if not line:
        raise SockCliRpcError("empty_response")
    doc = json.loads(line.decode("utf-8"))
    if not isinstance(doc, dict):
        raise SockCliRpcError("invalid_response")
    if "error" in doc and doc["error"] is not None:
        err = doc["error"]
        if isinstance(err, dict):
            msg = err.get("message", "error")
            code = err.get("code", -1)
            data = err.get("data")
            if data:
                raise SockCliRpcError(f"{code}:{msg}: {json.dumps(data, separators=(',', ':'))}")
            raise SockCliRpcError(f"{code}:{msg}")
        raise SockCliRpcError(str(err))
    return doc.get("result")


def _read_stdin_text() -> str:
    return sys.stdin.read()


def _read_stdin_bytes() -> bytes:
    buf = getattr(sys.stdin, "buffer", None)
    if buf is not None:
        return buf.read()
    return sys.stdin.read().encode("utf-8")


def _take_value(args: List[str], i: int, flag: str) -> Tuple[str, int]:
    tok = args[i]
    if "=" in tok:
        _, _, val = tok.partition("=")
        return val, i + 1
    if i + 1 >= len(args):
        raise SockCliUsageError(f"{flag} requires a value")
    return args[i + 1], i + 2


def _strip_global_flags(argv: List[str]) -> Tuple[List[str], Optional[float], bool]:
    out: List[str] = []
    timeout: Optional[float] = None
    want_help = False
    is_fetch = bool(argv and argv[0] == "fetch")
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in ("-h", "--help"):
            want_help = True
            i += 1
        elif tok == "--timeout" or tok.startswith("--timeout="):
            raw, i = _take_value(argv, i, "--timeout")
            try:
                timeout = float(raw)
            except ValueError as exc:
                raise SockCliUsageError("--timeout must be a number") from exc
            if timeout <= 0:
                raise SockCliUsageError("--timeout must be positive")
        elif tok == "--json" and not is_fetch:
            i += 1
        else:
            out.append(tok)
            if len(out) == 1 and out[0] == "fetch":
                is_fetch = True
            i += 1
    return out, timeout, want_help


def _parse_json_obj(raw: Optional[str], default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if raw is None:
        return {} if default is None else dict(default)
    text = _read_stdin_text() if raw == "-" else raw
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise SockCliUsageError("JSON params must be an object")
    return parsed


def _parse_fetch(args: List[str]) -> Tuple[str, Dict[str, Any]]:
    if not args:
        raise SockCliUsageError("usage: carnivore fetch <url> [-X METHOD] [-H 'Key: Val'] [-d BODY] [--json JSON] [--body-stdin]")
    url = ""
    method = "GET"
    headers: Dict[str, str] = {}
    body: Optional[str] = None
    i = 0
    while i < len(args):
        tok = args[i]
        if tok in ("-X", "--method") or tok.startswith("--method="):
            val, i = _take_value(args, i, tok.split("=")[0])
            method = val.upper()
        elif tok in ("-H", "--header") or tok.startswith("--header="):
            val, i = _take_value(args, i, tok.split("=")[0])
            k, sep, v = val.partition(":")
            if not sep or not k.strip():
                raise SockCliUsageError("header must be 'Name: Value'")
            headers[k.strip()] = v.lstrip()
        elif tok in ("-d", "--data", "--body") or tok.startswith(("--data=", "--body=")):
            val, i = _take_value(args, i, tok.split("=")[0])
            body = _read_stdin_text() if val in ("-", "@-") else val
        elif tok == "--json" or tok.startswith("--json="):
            val, i = _take_value(args, i, "--json")
            raw_json = _read_stdin_text() if val in ("-", "@-") else val
            parsed = json.loads(raw_json)
            body = json.dumps(parsed, separators=(",", ":"))
            if not any(h.lower() == "content-type" for h in headers):
                headers["Content-Type"] = "application/json"
        elif tok == "--body-stdin":
            body = _read_stdin_text()
            i += 1
        elif not tok.startswith("-") and not url:
            url = tok
            i += 1
        else:
            raise SockCliUsageError(f"unknown fetch argument: {tok}")
    if not url:
        raise SockCliUsageError("fetch requires a URL")
    params: Dict[str, Any] = {"url": url, "method": method, "headers": headers}
    if body is not None:
        params["body"] = body
    return "http.fetch", params


def _parse_sessions(rest: List[str]) -> Tuple[str, Dict[str, Any]]:
    if not rest:
        raise SockCliUsageError("usage: carnivore sessions <list|get|output|permission-mode|message|create|control> ...")
    sub = rest[0]
    tail = rest[1:]
    if sub == "list" and not tail:
        return "sessions.list", {}
    if sub == "get" and len(tail) == 1:
        return "sessions.get", {"ref": tail[0]}
    if sub == "permission-mode" and len(tail) == 1:
        return "sessions.permission_mode", {"ref": tail[0]}
    if sub == "output" and tail:
        ref = ""
        lines = 100
        i = 0
        while i < len(tail):
            tok = tail[i]
            if tok in ("--lines", "-n") or tok.startswith("--lines="):
                raw, i = _take_value(tail, i, tok.split("=")[0])
                lines = int(raw)
            elif not tok.startswith("-") and not ref:
                ref = tok
                i += 1
            else:
                raise SockCliUsageError(f"unknown sessions output argument: {tok}")
        if not ref:
            raise SockCliUsageError("sessions output requires <ref>")
        return "sessions.output", {"ref": ref, "lines": lines}
    if sub == "message":
        ref = ""
        line: Optional[str] = None
        token = ""
        i = 0
        while i < len(tail):
            tok = tail[i]
            if tok in ("--owner-token", "--token") or tok.startswith(("--owner-token=", "--token=")):
                token, i = _take_value(tail, i, tok.split("=")[0])
            elif tok == "-" and ref and line is None:
                line = _read_stdin_text().rstrip("\n")
                i += 1
            elif not tok.startswith("-"):
                if not ref:
                    ref = tok
                elif line is None:
                    line = tok
                else:
                    raise SockCliUsageError(f"unexpected argument: {tok}")
                i += 1
            else:
                raise SockCliUsageError(f"unknown sessions message argument: {tok}")
        if not ref or line is None or not token:
            raise SockCliUsageError("usage: carnivore sessions message <ref> <line> --owner-token <tok>")
        return "sessions.message", {"ref": ref, "line": line, "owner_token": token}
    if sub == "create":
        project: Optional[int] = None
        prompt: Optional[str] = None
        family: Optional[str] = None
        i = 0
        while i < len(tail):
            tok = tail[i]
            if tok == "--project" or tok.startswith("--project="):
                raw, i = _take_value(tail, i, "--project")
                project = int(raw)
            elif tok == "--prompt" or tok.startswith("--prompt="):
                prompt, i = _take_value(tail, i, "--prompt")
            elif tok == "--family" or tok.startswith("--family="):
                family, i = _take_value(tail, i, "--family")
            else:
                raise SockCliUsageError(f"unknown sessions create argument: {tok}")
        if project is None:
            raise SockCliUsageError("sessions create requires --project <int>")
        params: Dict[str, Any] = {"project": project}
        if prompt is not None:
            params["prompt"] = prompt
        if family is not None:
            params["family"] = family
        return "sessions.create", params
    if sub == "control" and len(tail) == 2:
        return "sessions.control", {"ref": tail[0], "action": tail[1]}
    raise SockCliUsageError("usage: carnivore sessions <list|get|output|permission-mode|message|create|control> ...")


def _parse_notify(rest: List[str]) -> Tuple[str, Dict[str, Any]]:
    if not rest:
        raise SockCliUsageError("usage: carnivore notify [toast] <title> [--ref <ref>] | notify alert <key> <severity> <title> [<json_params>]")
    if rest[0] == "alert":
        if len(rest) < 4 or len(rest) > 5:
            raise SockCliUsageError("usage: carnivore notify alert <key> <severity> <title> [<json_params>]")
        extra = _parse_json_obj(rest[4] if len(rest) == 5 else None, {})
        return "notify.alert", {"key": rest[1], "severity": rest[2], "title": rest[3], "params": extra}
    args = rest[1:] if rest[0] == "toast" and len(rest) >= 2 and not rest[1].startswith("-") else rest
    title = ""
    ref = "app"
    i = 0
    while i < len(args):
        tok = args[i]
        if tok == "--ref" or tok.startswith("--ref="):
            ref, i = _take_value(args, i, "--ref")
        elif not tok.startswith("-") and not title:
            title = tok
            i += 1
        else:
            raise SockCliUsageError(f"unknown notify argument: {tok}")
    if not title:
        raise SockCliUsageError("notify requires <title>")
    return "notify.toast", {"ref": ref, "title": title}


def _parse_storage(rest: List[str]) -> Tuple[str, Dict[str, Any]]:
    if not rest:
        raise SockCliUsageError("usage: carnivore storage <get|put|delete|list> ...")
    sub = rest[0]
    tail = rest[1:]
    if sub == "get" and len(tail) == 1:
        return "storage.get", {"key": tail[0]}
    if sub == "delete" and len(tail) == 1:
        return "storage.delete", {"key": tail[0]}
    if sub == "put" and len(tail) >= 2:
        key = tail[0]
        raw_val = _read_stdin_text() if tail[1] in ("--stdin", "-") else tail[1]
        if len(tail) > 2:
            raise SockCliUsageError("usage: carnivore storage put <key> (<value>|--stdin|-)")
        try:
            val: Any = json.loads(raw_val)
        except ValueError:
            val = raw_val
        return "storage.put", {"key": key, "value": val}
    if sub == "list":
        prefix = ""
        i = 0
        while i < len(tail):
            tok = tail[i]
            if tok == "--prefix" or tok.startswith("--prefix="):
                prefix, i = _take_value(tail, i, "--prefix")
            elif not tok.startswith("-") and not prefix:
                prefix = tok
                i += 1
            else:
                raise SockCliUsageError(f"unknown storage list argument: {tok}")
        return "storage.list", {"prefix": prefix}
    raise SockCliUsageError("usage: carnivore storage <get|put|delete|list> ...")


def _parse_projects(rest: List[str]) -> Tuple[str, Dict[str, Any]]:
    if rest == ["list"]:
        return "projects.list", {}
    if len(rest) == 3 and rest[0] == "git":
        return "projects.git", {"project": int(rest[1]), "op": rest[2]}
    if len(rest) == 3 and rest[0] == "snapshot":
        turn: Any = int(rest[2]) if rest[2].lstrip("-").isdigit() else rest[2]
        return "projects.snapshot", {"project": int(rest[1]), "turn": turn}
    raise SockCliUsageError("usage: carnivore projects <list | git <id> <op> | snapshot <id> <turn>>")


def _parse_exports(rest: List[str]) -> Tuple[str, Dict[str, Any]]:
    if len(rest) < 3 or rest[0] != "write":
        raise SockCliUsageError("usage: carnivore exports write <folder> <name> (--text TEXT | --bytes-b64 B64 | --stdin)")
    folder, name = rest[1], rest[2]
    b64: Optional[str] = None
    i = 3
    while i < len(rest):
        tok = rest[i]
        if tok == "--text" or tok.startswith("--text="):
            val, i = _take_value(rest, i, "--text")
            b64 = base64.b64encode(val.encode("utf-8")).decode("ascii")
        elif tok == "--bytes-b64" or tok.startswith("--bytes-b64="):
            b64, i = _take_value(rest, i, "--bytes-b64")
        elif tok == "--stdin":
            b64 = base64.b64encode(_read_stdin_bytes()).decode("ascii")
            i += 1
        else:
            raise SockCliUsageError(f"unknown exports write argument: {tok}")
    if b64 is None:
        raise SockCliUsageError("exports write requires --text, --bytes-b64, or --stdin")
    return "exports.write", {"folder": folder, "name": name, "bytes": b64}


def _parse_ai(rest: List[str]) -> Tuple[str, Dict[str, Any]]:
    if len(rest) < 3 or rest[0] != "call":
        raise SockCliUsageError("usage: carnivore ai call <feature> <capability> [<json_input> | --prompt TEXT [--max-tokens N]]")
    feature, capability = rest[1], rest[2]
    tail = rest[3:]
    inp: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    max_tokens: Optional[int] = None
    i = 0
    while i < len(tail):
        tok = tail[i]
        if tok == "--prompt" or tok.startswith("--prompt="):
            prompt, i = _take_value(tail, i, "--prompt")
        elif tok == "--max-tokens" or tok.startswith("--max-tokens="):
            raw, i = _take_value(tail, i, "--max-tokens")
            max_tokens = int(raw)
        elif not tok.startswith("-") or tok == "-":
            if inp is not None:
                raise SockCliUsageError(f"unexpected argument: {tok}")
            inp = _parse_json_obj(tok)
            i += 1
        else:
            raise SockCliUsageError(f"unknown ai call argument: {tok}")
    if inp is None:
        inp = {}
        if prompt is not None:
            inp["prompt"] = prompt
        if max_tokens is not None:
            inp["max_tokens"] = max_tokens
    return "ai.call", {"feature": feature, "capability": capability, "input": inp}


def _parse_mcp(rest: List[str]) -> Tuple[str, Dict[str, Any]]:
    if not rest or rest[0] not in ("config", "links"):
        raise SockCliUsageError("usage: carnivore mcp <config|links> [--session <ref>]")
    method = f"mcp.{rest[0]}"
    tail = rest[1:]
    session: Optional[str] = None
    i = 0
    while i < len(tail):
        tok = tail[i]
        if tok == "--session" or tok.startswith("--session="):
            session, i = _take_value(tail, i, "--session")
        elif not tok.startswith("-") and session is None:
            session = tok
            i += 1
        else:
            raise SockCliUsageError(f"unknown mcp argument: {tok}")
    return method, ({"session": session} if session is not None else {})


def _parse_flow(rest: List[str]) -> Tuple[str, Dict[str, Any]]:
    if not rest:
        raise SockCliUsageError("usage: carnivore flow <run|run-part|feed|tasks> ...")
    sub = rest[0]
    tail = rest[1:]
    if sub == "run" and tail:
        fid = tail[0]
        params: Dict[str, Any] = {"id": fid}
        i = 1
        while i < len(tail):
            tok = tail[i]
            if tok == "--seed" or tok.startswith("--seed="):
                params["seed"], i = _take_value(tail, i, "--seed")
            elif tok == "--start" or tok.startswith("--start="):
                raw, i = _take_value(tail, i, "--start")
                params["start"] = float(raw)
            elif tok == "--end" or tok.startswith("--end="):
                raw, i = _take_value(tail, i, "--end")
                params["end"] = float(raw)
            elif tok == "--refresh":
                params["refresh"] = True
                i += 1
            else:
                raise SockCliUsageError(f"unknown flow run argument: {tok}")
        return "flow.run", params
    if sub == "run-part" and len(tail) == 2:
        return "flow.run_part", {"token": tail[0], "index": int(tail[1])}
    if sub == "feed" and len(tail) >= 2:
        params = {"id": tail[0], "topic": tail[1]}
        i = 2
        while i < len(tail):
            tok = tail[i]
            if tok == "--seed" or tok.startswith("--seed="):
                params["seed"], i = _take_value(tail, i, "--seed")
            elif tok == "--start" or tok.startswith("--start="):
                raw, i = _take_value(tail, i, "--start")
                params["start"] = float(raw)
            elif tok == "--cursor" or tok.startswith("--cursor="):
                raw, i = _take_value(tail, i, "--cursor")
                params["cursor"] = float(raw)
            else:
                raise SockCliUsageError(f"unknown flow feed argument: {tok}")
        return "flow.feed", params
    if sub == "tasks":
        params = {}
        i = 0
        while i < len(tail):
            tok = tail[i]
            if tok == "--query" or tok.startswith("--query="):
                params["query"], i = _take_value(tail, i, "--query")
            elif tok == "--limit" or tok.startswith("--limit="):
                raw, i = _take_value(tail, i, "--limit")
                params["limit"] = int(raw)
            else:
                raise SockCliUsageError(f"unknown flow tasks argument: {tok}")
        return "flow.tasks", params
    raise SockCliUsageError("usage: carnivore flow <run|run-part|feed|tasks> ...")


def _build_request(argv: List[str]) -> Tuple[str, Dict[str, Any]]:
    if not argv:
        raise SockCliUsageError("usage: carnivore <command> [args...]")
    cmd = argv[0]
    rest = argv[1:]
    if cmd == "plugin":
        raise SockCliUsageError("carnivore plugin commands are disabled inside a plugin sandbox (CARNIVORE_PLUGIN_SOCK is set)")
    if cmd == "call":
        if not rest or len(rest) > 2:
            raise SockCliUsageError("usage: carnivore call <method> [<json_params>]")
        return rest[0], _parse_json_obj(rest[1] if len(rest) == 2 else None, {})
    if cmd == "sessions":
        return _parse_sessions(rest)
    if cmd == "notify":
        return _parse_notify(rest)
    if cmd == "fetch":
        return _parse_fetch(rest)
    if cmd == "storage":
        return _parse_storage(rest)
    if cmd == "projects":
        return _parse_projects(rest)
    if cmd == "exports":
        return _parse_exports(rest)
    if cmd == "ai":
        return _parse_ai(rest)
    if cmd == "ledger" and rest == ["read"]:
        return "ledger.read", {}
    if cmd == "topic" and rest and rest[0] == "publish" and len(rest) >= 2:
        params: Dict[str, Any] = {"name": rest[1]}
        i = 2
        while i < len(rest):
            tok = rest[i]
            if tok == "--key" or tok.startswith("--key="):
                params["key"], i = _take_value(rest, i, "--key")
            else:
                raise SockCliUsageError(f"unknown topic publish argument: {tok}")
        return "topic.publish", params
    if cmd == "ui" and rest and rest[0] == "invalidate" and len(rest) <= 2:
        return "ui.invalidate", ({"surface": rest[1]} if len(rest) == 2 else {})
    if cmd == "ui" and len(rest) >= 2 and rest[0] == "slot-publish":
        slot_name = rest[1]
        raw_items: Optional[str] = None
        if len(rest) == 3 and rest[2].startswith("--items="):
            raw_items = rest[2][8:]
        elif len(rest) == 3:
            raw_items = rest[2]
        elif len(rest) == 4 and rest[2] == "--items":
            raw_items = rest[3]
        elif len(rest) > 2:
            raise SockCliUsageError("usage: carnivore ui slot-publish <slot> [<json_items> | --items JSON]")
        if raw_items is None:
            items_list: List[Any] = []
        else:
            text = _read_stdin_text() if raw_items == "-" else raw_items
            parsed_items = json.loads(text)
            if not isinstance(parsed_items, list):
                raise SockCliUsageError("ui slot-publish items must be a JSON array")
            items_list = parsed_items
        return "ui.slot.publish", {"slot": slot_name, "items": items_list}
    if cmd == "process" and rest == ["snapshot"]:
        return "process.snapshot", {}
    if cmd == "mcp":
        return _parse_mcp(rest)
    if cmd == "flow":
        return _parse_flow(rest)
    if cmd == "service" and len(rest) >= 3 and rest[0] == "call":
        service_name, method_name = rest[1], rest[2]
        args_obj: Dict[str, Any] = {}
        if len(rest) == 4 and rest[3].startswith("--args="):
            args_obj = _parse_json_obj(rest[3][7:], {})
        elif len(rest) == 4:
            args_obj = _parse_json_obj(rest[3], {})
        elif len(rest) == 5 and rest[3] == "--args":
            args_obj = _parse_json_obj(rest[4], {})
        elif len(rest) > 3:
            raise SockCliUsageError("usage: carnivore service call <service> <method> [<json_args> | --args JSON]")
        params = {"service": service_name, "method": method_name, "args": args_obj}
        bus_tok = os.environ.get("CARNIVORE_BUS_TOKEN", "").strip()
        if bus_tok:
            params["_bus_token"] = bus_tok
        return "service.call", params
    if cmd in ("event", "events") and len(rest) >= 2 and rest[0] == "emit":
        if len(rest) > 3:
            raise SockCliUsageError("usage: carnivore event emit <event> [<json_payload>]")
        return "events.emit", {"event": rest[1], "payload": _parse_json_obj(rest[2] if len(rest) == 3 else None, {})}
    if cmd == "log" and len(rest) in (2, 3):
        return "log", {"level": rest[0], "event": rest[1], "fields": _parse_json_obj(rest[2] if len(rest) == 3 else None, {})}
    raise SockCliUsageError(f"unknown command: {' '.join(argv)}")


def _default_timeout(method: str, params: Dict[str, Any]) -> float:
    if method == "sessions.control" and params.get("action") == "stop":
        return SESSION_STOP_TIMEOUT_S
    if method == "ai.call":
        return AI_CALL_TIMEOUT_S
    return DEFAULT_TIMEOUT_S


def main(argv: Optional[List[str]] = None) -> int:
    raw_args = sys.argv[1:] if argv is None else list(argv)
    try:
        args, explicit_timeout, want_help = _strip_global_flags(raw_args)
    except ValueError as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    if want_help:
        sys.stdout.write(HELP_TEXT)
        sys.stdout.flush()
        return 0
    sock_path = os.environ.get("CARNIVORE_PLUGIN_SOCK", "").strip()
    if not sock_path:
        sys.stderr.write("CARNIVORE_PLUGIN_SOCK is not set\n")
        return 2
    try:
        method, params = _build_request(args)
    except (ValueError, IndexError) as exc:
        sys.stderr.write(f"{exc}\n")
        return 2
    timeout = explicit_timeout if explicit_timeout is not None else _default_timeout(method, params)
    try:
        result = rpc_call(sock_path, method, params, timeout=timeout)
    except Exception as exc:  # noqa: BLE001
        sys.stderr.write(f"{exc}\n")
        return 1
    sys.stdout.write(json.dumps(result, separators=(",", ":")) + "\n")
    sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
