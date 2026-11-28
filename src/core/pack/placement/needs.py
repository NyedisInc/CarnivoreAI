
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple
from src.core.pack.errors.input_error import PackInputError

TOOLS = ("python3.12", "python3", "node", "npm", "git", "gh", "docker", "tmux", "claude", "playwright", "playwright_browsers",
         "ffmpeg", "ffprobe", "codex", "agy", "blender", "brew")
_FLAGS = ("xcode", "ios_sim")
_GPUS = ("gpu", "gpu:nvidia", "gpu:amd", "gpu:apple", "cuda")
_MINS = ("vram_gb", "mem_gb", "cores", "disk_gb")
_OSES, _ARCHES = ("macos", "linux", "windows"), ("arm64", "x86_64")
_MIN_RE = re.compile(r"^([a-z_]+)>=(\d{1,6}(?:\.\d{1,2})?)$")
_LABEL_RE = re.compile(r"[a-z0-9][a-z0-9 ._-]{0,31}")
VOCAB = TOOLS + _FLAGS + _GPUS + tuple(f"{m}>=N" for m in _MINS) + tuple(f"os:{o}" for o in _OSES) + \
    tuple(f"arch:{a}" for a in _ARCHES) + ("label:<text>",)
KNOWN_WORDS = ", ".join(VOCAB)


@dataclass(frozen=True)
class Need:

    kind: Literal["tool", "gpu", "min", "os", "arch", "label"]
    name: str
    value: Optional[float] = None

    @property
    def text(self) -> str:
        if self.kind == "min":
            return f"{self.name}>={self.value:g}"
        if self.kind == "gpu":
            return "gpu" if self.name == "gpu" else f"gpu:{self.name}"
        return self.name if self.kind == "tool" else f"{self.kind}:{self.name}"


def parse_need(text: str) -> Need:
    word = str(text).strip().lower()
    if word in TOOLS or word in _FLAGS:
        return Need("tool", word)
    if word == "gpu":
        return Need("gpu", "gpu")
    if word == "cuda":
        return Need("gpu", "nvidia")
    if word in _GPUS:
        return Need("gpu", word.split(":", 1)[1])
    found = _MIN_RE.match(word)
    if found and found.group(1) in _MINS:
        return Need("min", found.group(1), float(found.group(2)))
    for kind, allowed in (("os", _OSES), ("arch", _ARCHES)):
        if word.startswith(kind + ":") and word[len(kind) + 1:] in allowed:
            return Need(kind, word[len(kind) + 1:])  # type: ignore[arg-type]
    if word.startswith("label:") and _LABEL_RE.fullmatch(word[6:].strip()):
        return Need("label", word[6:].strip())
    raise PackInputError(f"unknown requirement {str(text)[:40]!r}; the known words are: {KNOWN_WORDS}")


def parse_all(words: Any, *, limit: int = 8) -> List[Need]:
    if words is None:
        return []
    if not isinstance(words, (list, tuple)) or len(words) > limit:
        raise PackInputError(f"give a list of at most {limit} words; the known words are: {KNOWN_WORDS}")
    return _dedupe([parse_need(w) for w in words])


def _dedupe(items: List[Need]) -> List[Need]:
    return list(dict.fromkeys(items))


def _num(value: Any) -> Optional[float]:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _tool(snapshot: Dict[str, Any], can: Optional[Dict[str, Any]], name: str) -> Optional[bool]:
    if can is not None:
        tools = _dict(can.get("tools"))
        if isinstance(tools.get(name), bool):
            return tools[name]
        if name == "xcode" and "xcode" in can:
            return bool(can.get("xcode"))
        if name == "ios_sim" and isinstance(can.get("ios_sim"), bool):
            return can["ios_sim"]
        if name == "brew" and isinstance(can.get("brew"), bool):
            return can["brew"]
    if name in _FLAGS:
        return None
    flag = _dict(snapshot.get("toolchain")).get(name)
    return flag if isinstance(flag, bool) else None


def _gpu(can: Optional[Dict[str, Any]], vendor: str) -> Optional[bool]:
    gpus = can.get("gpus") if can is not None else None
    if not isinstance(gpus, list):
        return None
    for g in (g for g in gpus if isinstance(g, dict)):
        if vendor == "gpu":
            if g.get("discrete") is True or g.get("vendor") == "apple":
                return True
        elif g.get("vendor") == vendor:
            return True
    return False


def _minimum(snapshot: Dict[str, Any], can: Optional[Dict[str, Any]], name: str) -> Optional[float]:
    specs, load = _dict(snapshot.get("specs")), _dict(snapshot.get("load"))
    if name == "disk_gb":
        return _num(load.get("disk_free_gb"))
    if name == "vram_gb":
        gpus = can.get("gpus") if can is not None else None
        if not isinstance(gpus, list):
            return None
        return max([v for v in (_num(_dict(g).get("vram_gb")) for g in gpus) if v is not None] or [0.0])
    if name == "cores":
        return _num((can or {}).get("cores")) or _num(specs.get("cores")) or _num(load.get("cores"))
    return _num((can or {}).get("mem_gb")) or _num(specs.get("mem_total_gb")) or _num(load.get("mem_total_gb"))


def _os_arch(snapshot: Dict[str, Any], can: Optional[Dict[str, Any]], kind: str) -> Optional[str]:
    specs = _dict(snapshot.get("specs"))
    if kind == "arch":
        raw = str((can or {}).get("arch") or specs.get("arch") or "").lower()
        return {"arm64": "arm64", "aarch64": "arm64", "x86_64": "x86_64", "amd64": "x86_64"}.get(raw)
    raw = str((can or {}).get("os") or specs.get("os") or "").lower()
    for word, family in (("darwin", "macos"), ("macos", "macos"), ("linux", "linux"), ("windows", "windows")):
        if raw.startswith(word):
            return family
    return None


def meets(snapshot: Optional[Dict[str, Any]], need: Need) -> Optional[bool]:
    if not isinstance(snapshot, dict):
        return None
    can = snapshot.get("can") if isinstance(snapshot.get("can"), dict) else None
    if need.kind == "tool":
        return _tool(snapshot, can, need.name)
    if need.kind == "gpu":
        return _gpu(can, need.name)
    if need.kind == "min":
        have = _minimum(snapshot, can, need.name)
        return None if have is None else have >= (need.value or 0.0)
    if need.kind in ("os", "arch"):
        have_word = _os_arch(snapshot, can, need.kind)
        return None if have_word is None else have_word == need.name
    labels = can.get("labels") if can is not None else None
    own_label = str(snapshot.get("label") or "").strip().lower()
    if own_label and need.name == own_label:
        return True
    return None if not isinstance(labels, list) else need.name in labels


def unmet_reason(snapshot: Optional[Dict[str, Any]], need: Need) -> Optional[str]:
    got = meets(snapshot, need)
    if got is True:
        return None
    if got is False:
        return f"lacks {need.text}"
    old = not isinstance(_dict(snapshot).get("can"), dict)
    return f"has not reported whether it has {need.text}" + (" (needs an app update)" if old else "")


_STRICT = {"xcodebuild": "xcode", "xcrun": "xcode", "ffmpeg": "ffmpeg", "ffprobe": "ffmpeg", "blender": "blender", "node": "node",
           "npm": "node", "npx": "node", "gh": "gh", "docker": "docker", "python3.12": "python3.12"}
_FILTER = {"playwright": "playwright_browsers"}
_SKIP = {"env", "time", "nice", "nohup", "command", "exec"}
_SEPARATORS = {"&&", "||", ";", "|", "&", ";;", "|&"}


def _segments(command: str) -> List[List[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    out: List[List[str]] = [[]]
    for token in lexer:
        if token in _SEPARATORS:
            out.append([])
        else:
            out[-1].append(token)
    return [s for s in out if s]


def _programs(words: List[str]) -> List[str]:
    i = 0
    while i < len(words):
        w = words[i]
        if w in _SKIP or w.startswith("-") or w.isdigit() or re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w):
            i += 1
            continue
        names = [w.rsplit("/", 1)[-1]]
        if names[0] == "npx":
            rest = [x for x in words[i + 1:] if not x.startswith("-")]
            names += [rest[0].rsplit("/", 1)[-1]] if rest else []
        return names
    return []


def from_command(command: str) -> Tuple[List[Need], List[Need], List[Need]]:
    try:
        segments = _segments(str(command))
    except ValueError:
        return [], [], []
    strict: List[Need] = []
    filters: List[Need] = []
    for words in segments:
        for name in _programs(words):
            if name in _STRICT:
                strict.append(Need("tool", _STRICT[name]))
            if name in _FILTER:
                filters.append(Need("tool", _FILTER[name]))
    return _dedupe(strict), _dedupe(filters), []


def kind_defaults(kind: str) -> Tuple[List[Need], List[Need]]:
    if kind == "browser":
        return [Need("tool", "playwright_browsers")], []
    if kind == "render":
        return [], [Need("gpu", "gpu"), Need("tool", "ffmpeg")]
    return [], []
