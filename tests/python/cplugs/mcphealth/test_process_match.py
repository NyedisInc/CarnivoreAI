
import subprocess
import sys
import time

from src.core.conversation_writers import read_process_table
from src.core.mcp_health import process_match
from src.core.mcp_health.servers import ServerSpec

MARK = "carnivore-mcp-stdio-fixture-1678"
PARENT = (
    "import subprocess, sys, time\n"
    f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)', '{MARK}'])\n"
    "print(c.pid, flush=True)\n"
    "sys.stdin.readline()\n"
    "c.terminate(); c.wait()\n"
    "print('ended', flush=True)\n"
    "time.sleep(60)\n"
)


def _alive(spec, parent_pid):
    table = read_process_table()
    commands = {pid: row.command for pid, row in table.rows.items()}
    return process_match.alive(spec, parent_pid, commands, table.children)


def test_a_stdio_child_reads_alive_then_down_while_its_parent_lives():
    spec = ServerSpec("fixture", "stdio", command=sys.executable, args=("-c", "import time; time.sleep(60)", MARK))
    parent = subprocess.Popen([sys.executable, "-c", PARENT], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        int(parent.stdout.readline())
        assert _alive(spec, parent.pid) is True
        parent.stdin.write("\n")
        parent.stdin.flush()
        assert parent.stdout.readline().strip() == "ended"
        time.sleep(0.2)
        assert parent.poll() is None
        assert _alive(spec, parent.pid) is False
    finally:
        parent.kill()
        parent.wait()
    assert _alive(spec, parent.pid) is None


def test_npm_title_and_basename_matches_and_tool_shells_are_skipped():
    npx = ServerSpec("memory", "stdio", command="npx", args=("-y", "@modelcontextprotocol/server-memory"))
    assert process_match.matches(npx, "npm exec @modelcontextprotocol/server-memory")
    assert not process_match.matches(npx, "npm exec @modelcontextprotocol/server-everything")
    bare = ServerSpec("bin", "stdio", command="/opt/tools/my-server")
    assert process_match.matches(bare, "node /opt/tools/my-server")
    assert not process_match.matches(bare, "node /opt/tools/other --my-server")
    templated = ServerSpec("t", "stdio", command="${HOME}/x", args=("${TOKEN}",))
    assert not process_match.matches(templated, "/Users/me/x secret")
    commands = {1: "claude", 2: "/bin/zsh -c source /p/shell-snapshots/snapshot-zsh-1.sh && npx", 3: "npm exec @modelcontextprotocol/server-memory"}
    children = {1: [2], 2: [3]}
    assert process_match.alive(npx, 1, commands, children) is False
