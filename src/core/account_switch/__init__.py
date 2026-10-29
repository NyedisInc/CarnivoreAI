"""Provider account switching: which login new sessions launch under.

THE MECHANISM IS A POINTER, NEVER A TOKEN. Every managed account already
has its own login directory under ``~/.carnivore/accounts/<id>``.
"Switching" chooses which account's directory becomes
``CLAUDE_CONFIG_DIR`` (or ``CODEX_HOME``) for the sessions this app
launches. Nothing in this package opens a keychain item, a
``.credentials.json`` or an ``auth.json``, and nothing refreshes a token:
the Claude refresh token is single use, so a second holder logs the
first one out (``docs/provider-ledger.md``).

ONE MODULE PER QUESTION.

- :mod:`store` reads and writes the ``provider_account_switch`` block
  through the one config writer.
- :mod:`shared_links` makes a profile able to RESUME a conversation that
  began under another account, by linking the profile's transcript
  directory to the shared one. Created only if absent, never overwriting.
- :mod:`launch_env` is the variable a new or restarted pane is given.
- :mod:`decide` is the pure auto-switch rule: same provider only, never
  an expired or unchecked login, only at or past the threshold.
- :mod:`auto_switch` runs that rule after each ledger poll and moves the
  pointer. It NEVER restarts a running session (see its docstring).
- :mod:`pane_account` reads which profile a running pane was given, so
  the providers page can offer "restart to switch" for the sessions
  still on another account.
- :mod:`profile_setup` makes a managed claude profile launchable: its
  first-run setup marked done once its login reads ok, its copies of the
  shared MCP servers removed, the default login's folder trust copied in,
  and the read every switch path gates on (#671, #704).
- :mod:`shared_mcp` is the one MCP server file every claude launch loads
  (``--mcp-config``), kept up to date on each ledger pass (#704).
- :mod:`auto_restart` and :mod:`restart_timer` rotate a claude session
  frozen on its limit onto the next account and type ``continue``, after
  each ledger pass and every 15 seconds (#521, #672, #2035);
  :mod:`limit_rotate` and :mod:`rotate_state` are its collaborators and
  its durable per-record memo.
"""
