
from __future__ import annotations

import os
import re
import stat
from pathlib import Path
from typing import Optional, Tuple


class BackRouteInvalid(Exception):
    pass


SOCKET_PATH_MAX = 103
FALLBACK_ROOT = "/tmp"
NONCE_HEX = 8

Route = Tuple[str, object, str]


def name_pattern(grant_id: str) -> "re.Pattern[str]":
    return re.compile(rf"^in-{re.escape(grant_id)}-[A-Za-z0-9]{{1,32}}\.sock$")


def _user_temp_dir() -> Optional[str]:
    try:
        return os.confstr("CS_DARWIN_USER_TEMP_DIR") or None
    except (AttributeError, ValueError, OSError):
        return None


def _is_private_dir(path: "Path | str") -> bool:
    try:
        st = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == os.getuid() and not stat.S_IMODE(st.st_mode) & 0o077


def socket_dir(directory: Path, grant_id: str) -> Path:
    name = f"in-{grant_id}-{'0' * NONCE_HEX}.sock"
    if len(os.fsencode(str(directory / name))) <= SOCKET_PATH_MAX:
        return directory
    user_tmp = _user_temp_dir()
    if user_tmp is not None and _is_private_dir(user_tmp) and len(os.fsencode(str(Path(user_tmp) / name))) <= SOCKET_PATH_MAX:
        return Path(user_tmp)
    fallback = Path(FALLBACK_ROOT) / f"carnivore-{os.getuid()}"
    try:
        os.mkdir(fallback, 0o700)
    except FileExistsError:
        pass
    except OSError as exc:
        raise BackRouteInvalid(f"the back socket directory {fallback} cannot be made: {exc.strerror}") from None
    if not os.path.lexists(fallback):
        raise BackRouteInvalid(f"the back socket directory {fallback} cannot be read")
    if not _is_private_dir(fallback):
        raise BackRouteInvalid(f"the back socket directory {fallback} is not a private directory of this user")
    if len(os.fsencode(str(fallback / name))) > SOCKET_PATH_MAX:
        raise BackRouteInvalid("no back socket path fits the unix socket length limit")
    return fallback


def validate(directory: Path, grant_id: str, kind: str, path: Optional[str], port: Optional[int],
             route_id: Optional[str] = None) -> Route:
    if kind == "tcp":
        if port is None or not route_id or re.fullmatch(r"[A-Za-z0-9]{8,64}", route_id) is None:
            raise BackRouteInvalid("a tcp route needs a port and a route id")
        return ("tcp", port, route_id)
    directory = socket_dir(directory, grant_id)
    try:
        dir_stat = os.lstat(directory)
        real = Path(os.path.realpath(path or ""))
        sock_stat = os.lstat(real)
    except OSError:
        raise BackRouteInvalid("the route back is not there") from None
    if (not stat.S_ISDIR(dir_stat.st_mode) or dir_stat.st_uid != os.getuid()
            or stat.S_IMODE(dir_stat.st_mode) & 0o077
            or real.parent != Path(os.path.realpath(directory)) or not name_pattern(grant_id).match(real.name)
            or not stat.S_ISSOCK(sock_stat.st_mode) or sock_stat.st_uid != os.getuid()):
        raise BackRouteInvalid("the route back is not ours to trust")
    return ("unix", str(real), "")
