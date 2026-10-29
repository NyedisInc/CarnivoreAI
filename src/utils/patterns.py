
import re
import socket
from typing import Optional, Dict, List, Callable
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()



def is_valid_dev_port(port: int) -> bool:
    try:
        port_int = int(port)
    except (TypeError, ValueError):
        return False
    return 1024 <= port_int <= 65535


def port_is_listening(port: int, timeout_ms: int = 250) -> bool:
    if not is_valid_dev_port(port):
        return False

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(max(0.001, timeout_ms / 1000.0))
        return sock.connect_ex(("127.0.0.1", int(port))) == 0
    except OSError:
        return False
    finally:
        try:
            sock.close()
        except OSError:
            pass


@dataclass
class PatternMatch:
    pattern_name: str
    matched_text: str
    groups: tuple
    line_number: int


class PatternDetector:

    PATTERNS = {
        "localhost_server": re.compile(
            r"(?:https?://)?localhost:(\d{2,5})\b|"
            r"(?:https?://)?127\.0\.0\.1:(\d{2,5})\b|"
            r"(?:https?://)?0\.0\.0\.0:(\d{2,5})\b|"
            r"(?:https?://)?(?:\[::\]|\[::1\]):(\d{2,5})\b"
        ),

        "server_ready": re.compile(
            r"(?:server|development server|dev server).*?"
            r"(?:running|listening|started|ready|available)",
            re.IGNORECASE,
        ),

        "listening_on_port": re.compile(
            r"\b(?:listening|serving|bound|bind)\s+(?:on|at)\s+"
            r"(?:port\s+)?(\d{2,5})\b",
            re.IGNORECASE,
        ),

        "port_keyword": re.compile(
            r"\bport\s+(\d{2,5})\b",
            re.IGNORECASE,
        ),

        "url_with_port": re.compile(
            r"https?://[^\s/:]+:(\d{2,5})\b",
        ),

        "error": re.compile(
            r"(?:ERROR|Error|error|FAIL|Failed|failed):",
            re.IGNORECASE,
        ),

        "warning": re.compile(
            r"(?:WARNING|Warning|warning|WARN):",
            re.IGNORECASE,
        ),

        "file_created": re.compile(
            r"(?:Created|Writing|Saved|Wrote).*?(?:file|to):\s*(.+)",
            re.IGNORECASE,
        ),

        "build_complete": re.compile(
            r"(?:build|compilation|compile).*?(?:complete|successful|finished|done)",
            re.IGNORECASE,
        ),

        "test_result": re.compile(
            r"(?:tests?|specs?).*?(?:passed|failed|complete|finished)",
            re.IGNORECASE,
        ),
    }

    def __init__(self):
        self.callbacks: Dict[str, List[Callable]] = {}

    def register_callback(self, pattern_name: str, callback: Callable[[PatternMatch], None]):
        if pattern_name not in self.callbacks:
            self.callbacks[pattern_name] = []
        self.callbacks[pattern_name].append(callback)
        logger.debug("pattern_callback_registered", pattern=pattern_name)

    def detect_patterns(self, text: str, line_number: int = 0) -> List[PatternMatch]:
        matches = []

        for pattern_name, regex in self.PATTERNS.items():
            match = regex.search(text)
            if match:
                pattern_match = PatternMatch(
                    pattern_name=pattern_name,
                    matched_text=match.group(0),
                    groups=match.groups(),
                    line_number=line_number,
                )
                matches.append(pattern_match)

                logger.debug(
                    "pattern_detected",
                    pattern=pattern_name,
                    length=len(text),
                    line=line_number,
                )

                if pattern_name in self.callbacks:
                    for callback in self.callbacks[pattern_name]:
                        try:
                            callback(pattern_match)
                        except Exception as e:
                            logger.error(
                                "pattern_callback_error",
                                pattern=pattern_name,
                                error=str(e),
                            )

        return matches

    def extract_port(self, text: str) -> Optional[int]:
        for pattern_name in (
            "localhost_server",
            "url_with_port",
            "listening_on_port",
            "port_keyword",
        ):
            regex = self.PATTERNS[pattern_name]
            match = regex.search(text)
            if not match:
                continue
            for group in match.groups():
                if not group:
                    continue
                try:
                    candidate = int(group)
                except (TypeError, ValueError):
                    continue
                if is_valid_dev_port(candidate):
                    return candidate
        return None

    def is_server_ready(self, text: str) -> bool:
        return bool(self.PATTERNS["server_ready"].search(text))

    def has_error(self, text: str) -> bool:
        return bool(self.PATTERNS["error"].search(text))

    def has_warning(self, text: str) -> bool:
        return bool(self.PATTERNS["warning"].search(text))


_DEFAULT_DETECTOR: Optional[PatternDetector] = None


def _detector() -> PatternDetector:
    global _DEFAULT_DETECTOR
    if _DEFAULT_DETECTOR is None:
        _DEFAULT_DETECTOR = PatternDetector()
    return _DEFAULT_DETECTOR


def extract_port(text: str) -> Optional[int]:
    return _detector().extract_port(text)
