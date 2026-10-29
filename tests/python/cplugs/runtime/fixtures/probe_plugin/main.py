
import ctypes
import json
import os
import socket
import subprocess

from cplug_sdk import Plugin

plugin = Plugin()


def attempt(fn):
    try:
        fn()
        return "ALLOWED"
    except Exception as exc:  # noqa: BLE001
        return type(exc).__name__


def read_file(path):
    with open(path) as f:
        f.read(1)


def connect(port):
    socket.create_connection(("127.0.0.1", port), 1).close()


def sysctl(mib):
    libc = ctypes.CDLL(None, use_errno=True)
    arr = (ctypes.c_int * len(mib))(*mib)
    size = ctypes.c_size_t(0)
    if libc.sysctl(arr, len(mib), None, ctypes.byref(size), None, 0) != 0:
        raise OSError(ctypes.get_errno(), "sysctl")


@plugin.on_event("probe")
async def probe(seq, payload):
    inside = os.path.join(os.getcwd(), "inside.txt")
    results = {
        "read_secret": attempt(lambda: read_file(payload["secret"])),
        "read_other_plugin": attempt(lambda: read_file(payload["other"])),
        "list_tmp": attempt(lambda: os.listdir("/private/tmp")),
        "connect_loopback": attempt(lambda: connect(payload["port"])),
        "exec_sh": attempt(lambda: subprocess.run(["/bin/sh", "-c", "true"], check=True)),
        "write_outside": attempt(lambda: open(payload["outside"], "w").close()),
        "write_inside": attempt(lambda: open(inside, "w").close()),
        "list_procs": attempt(lambda: sysctl([1, 14, 0])),
        "procargs_of_parent": attempt(lambda: sysctl([1, 49, os.getppid()])),
        "env_keys": sorted(os.environ),
    }
    await plugin.host.storage.put(key="probe", value=results)


@plugin.on_event("alloc")
async def alloc(seq, payload):
    plugin.hold = b"x" * int(payload["mb"]) * 1024 * 1024
    await plugin.host.storage.put(key="alloc", value="held")


@plugin.on_event("raw")
async def raw(seq, payload):
    line = json.dumps({"jsonrpc": "2.0", "id": 7, "method": "log", "params": {"level": "info", "event": "x", "fields": {}}})
    os.write(1, (line + "\n" + line + "\n").encode())
