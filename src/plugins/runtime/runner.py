
import asyncio
import importlib
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
    runtime_dir, code_dir, entry = os.path.dirname(os.path.abspath(__file__)), argv[1], argv[2]
    sys.path[:0] = [runtime_dir, code_dir]
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
