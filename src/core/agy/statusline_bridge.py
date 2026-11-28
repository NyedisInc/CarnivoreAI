
import json
import os
import sys
import time

KEPT = ("agent_state", "tool_confirmation_pending", "conversation_id", "transcript_path", "model", "context_window",
        "quota", "email", "plan_tier", "cost", "cwd", "cycle_mode", "subagents", "task_count", "version")

_RESET, _DIM, _CYAN, _GREEN, _YELLOW, _RED = "\033[0m", "\033[2m", "\033[36m", "\033[32m", "\033[33m", "\033[31m"


def keep(payload: dict) -> dict:
    return {key: payload[key] for key in KEPT if key in payload}


def write_state(directory: str, pid: str, state: dict) -> None:
    if not pid.isdigit():
        return
    try:
        os.makedirs(directory, mode=0o700, exist_ok=True)
        path = os.path.join(directory, pid + ".json")
        body = json.dumps(state, sort_keys=True)
        try:
            with open(path, encoding="utf-8") as handle:
                old = json.load(handle)
            old.pop("written_at", None)
            if json.dumps(old, sort_keys=True) == body:
                return
        except (OSError, ValueError):
            pass
        state = dict(state, written_at=time.time())
        tmp = "%s.%d.tmp" % (path, os.getpid())
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(state, handle, sort_keys=True)
        os.replace(tmp, path)
    except OSError:
        pass


def _bar(percent: float, width: int = 10) -> str:
    filled = max(0, min(width, int(round(percent / 100.0 * width))))
    return "▓" * filled + "░" * (width - filled)


def _quota(quota: object) -> str:
    best = None
    for bucket in (quota or {}).values() if isinstance(quota, dict) else ():
        if not isinstance(bucket, dict):
            continue
        frac = 0.0 if bucket.get("disabled") else bucket.get("remaining_fraction")
        if isinstance(frac, (int, float)) and (best is None or frac < best):
            best = float(frac)
    if best is None:
        return ""
    color = _RED if best <= 0.10 else _YELLOW if best <= 0.30 else _GREEN
    return "%squota %d%%%s" % (color, round(best * 100), _RESET)


def render(payload: dict) -> str:
    parts = []
    mode = payload.get("cycle_mode")
    if mode:
        parts.append("%s%s%s" % (_DIM, mode, _RESET))
    model = payload.get("model") if isinstance(payload.get("model"), dict) else {}
    if model.get("display_name"):
        effort = model.get("effort")
        shown = effort and effort.lower() not in model["display_name"].lower()
        parts.append("%s%s%s%s" % (_CYAN, model["display_name"], _RESET, (" " + effort) if shown else ""))
    window = payload.get("context_window") if isinstance(payload.get("context_window"), dict) else {}
    used = window.get("used_percentage")
    if isinstance(used, (int, float)):
        parts.append("%s %d%%" % (_bar(float(used)), round(used)))
    quota = _quota(payload.get("quota"))
    if quota:
        parts.append(quota)
    cost = payload.get("cost") if isinstance(payload.get("cost"), dict) else {}
    if isinstance(cost.get("total_usd"), (int, float)) and cost["total_usd"] > 0:
        parts.append("$%.2f" % cost["total_usd"])
    if payload.get("tool_confirmation_pending"):
        parts.append("%sneeds you%s" % (_YELLOW, _RESET))
    return " · ".join(parts)


def main(argv: list) -> int:
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    if len(argv) >= 3:
        write_state(argv[1], argv[2], keep(payload))
    sys.stdout.write(render(payload))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
