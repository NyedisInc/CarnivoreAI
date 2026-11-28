
import os
import resource
import sys


def main(argv):
    if len(argv) != 5:
        sys.stderr.write("usage: runner.py <code_dir> <entry> <open_files> <fsize_bytes>\n")
        return 2
    nofile, fsize = int(argv[3]), int(argv[4])
    resource.setrlimit(resource.RLIMIT_NOFILE, (nofile, nofile))
    resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))

    orig_prefix = sys.pycache_prefix
    sys.pycache_prefix = None
    try:
        import asyncio
        import importlib
        import json  # noqa: F401
        import typing  # noqa: F401
        from pathlib import Path
    finally:
        sys.pycache_prefix = orig_prefix

    runtime_dir, code_dir, entry = os.path.dirname(os.path.abspath(__file__)), argv[1], argv[2]
    sys.path[:0] = [runtime_dir, code_dir]
    code_real = Path(os.path.realpath(code_dir))
    extra_site = os.environ.pop("CARNIVORE_EXTRA_SITE", "")
    for raw_site in extra_site.split(os.pathsep):
        if not raw_site:
            continue
        site_real = Path(os.path.realpath(raw_site))
        if site_real.is_relative_to(code_real) and site_real.is_dir():
            site_str = str(site_real)
            if site_str not in sys.path:
                sys.path.append(site_str)
    protocol_out = sys.stdout
    sys.stdout = sys.stderr
    module = importlib.import_module(entry)
    plugin = getattr(module, "plugin", None)
    if plugin is None:
        sys.stderr.write("the entry module has no `plugin`\n")
        return 3
    asyncio.run(plugin.serve(out=protocol_out.buffer))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
