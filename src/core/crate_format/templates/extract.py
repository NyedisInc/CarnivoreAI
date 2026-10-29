"""Rebuild every file of a carnivore crate with nothing but python 3 (format 1; see README.txt in the crate).

usage: python3 extract.py <crate> <empty out dir>

Each file of files.jsonl is written to <out>/<home>[-<index>]/<rel> from its chunks, then checked against its sha256.
Members are read one by one; nothing is ever unpacked by tar itself. exit 0 ok, 1 a hash mismatch, 2 could not run.
"""

import hashlib
import json
import lzma
import os
import re
import subprocess
import sys
import tarfile

try:
    from compression import zstd
except ImportError:
    zstd = None

TOKEN = re.compile(r"[a-z][a-z0-9_-]{0,31}")
BAD_STREAM = (lzma.LZMAError,) + ((zstd.ZstdError,) if zstd is not None else ())


class Fail(Exception):
    pass


def unzstd(packed, length):
    if zstd is not None:
        out = zstd.ZstdDecompressor().decompress(packed, length + 1)
    else:
        try:
            out = subprocess.run(["zstd", "-d", "-c"], input=packed, capture_output=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError) as exc:
            raise Fail("this python has no zstd and the zstd command failed: %s" % exc)
    return out


def unxz(packed, length):
    return lzma.LZMADecompressor().decompress(packed, length + 1)


def safe_rel(rel):
    parts = rel.split("/") if isinstance(rel, str) else [""]
    if not rel or rel.startswith("/") or "\x00" in rel or any(p in ("", ".", "..") for p in parts):
        raise Fail("unsafe path in files.jsonl: %r" % (rel,))
    return parts


def member_bytes(tar, name):
    try:
        info = tar.getmember(name)
    except KeyError:
        raise Fail("member %s is missing" % name)
    if not info.isreg():
        raise Fail("member %s is not a regular file" % name)
    return tar.extractfile(info).read()


def chunk(tar, names, sha, length):
    for ext, undo in ((".zst", unzstd), (".xz", unxz)):
        name = "blobs/%s/%s%s" % (sha[:2], sha, ext)
        if name in names:
            try:
                raw = undo(member_bytes(tar, name), length)
            except BAD_STREAM:
                return None
            if len(raw) != length or hashlib.sha256(raw).hexdigest() != sha:
                return None
            return raw
    raise Fail("chunk %s has no blob" % sha)


def extract(crate, out):
    with open(crate, "rb") as handle:
        if handle.read(21) == b"age-encryption.org/v1":
            raise Fail("this crate is encrypted; open it first with: age -d -i <identity file> %s > x.crate" % crate)
    if os.path.exists(out) and os.listdir(out):
        raise Fail("the destination %s is not empty" % out)
    os.makedirs(out, mode=0o700, exist_ok=True)
    bad = 0
    with tarfile.open(crate, "r:") as tar:
        names = set(tar.getnames())
        for line in member_bytes(tar, "files.jsonl").splitlines():
            rec = json.loads(line)
            if not TOKEN.fullmatch(str(rec["home"])) or not isinstance(rec["home_index"], int):
                raise Fail("unsafe home in files.jsonl: %r" % (rec["home"],))
            home = rec["home"] if rec["home_index"] == 0 else "%s-%d" % (rec["home"], rec["home_index"])
            target = os.path.join(out, home, *safe_rel(rec["rel"]))
            os.makedirs(os.path.dirname(target), mode=0o700, exist_ok=True)
            digest, whole = hashlib.sha256(), True
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0), 0o600)
            with os.fdopen(fd, "wb") as dst:
                for sha, length in rec["chunks"]:
                    raw = chunk(tar, names, sha, length)
                    if raw is None:
                        whole = False
                        continue
                    digest.update(raw)
                    dst.write(raw)
            if not whole or digest.hexdigest() != rec["content_sha256"]:
                bad += 1
                print("MISMATCH %s/%s" % (home, rec["rel"]))
            else:
                print("ok %s/%s" % (home, rec["rel"]))
    return bad


def main(argv):
    if len(argv) != 3:
        print(__doc__.strip().splitlines()[2], file=sys.stderr)
        return 2
    errors = (Fail, OSError, tarfile.TarError, ValueError, KeyError, TypeError) + BAD_STREAM
    try:
        bad = extract(argv[1], argv[2])
    except errors as exc:
        print("could not extract: %s" % exc, file=sys.stderr)
        return 2
    print("%d files did not match" % bad if bad else "every file matched")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
