"""
- ``persist.py``: the small sqlite file (``agent_actions.db`` under the state dir) that keeps every pending action and
  recent decision across a server restart.
- ``call_context.py``: the ONE place a tool call and its replay record ride from the dispatcher to ``park``.
- ``runtime.py``: the approve-time re-checks and the REPLAY of an action restored from disk.
- ``wording.py``: the plain sentence a row shows ("type 'ls' + Enter into switch sparky").

``docs/mcp-server.md`` carries the rules.
"""
