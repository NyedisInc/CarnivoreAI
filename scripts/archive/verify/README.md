# Archived one-off verify scripts

Each script here was a real-browser or real-server pixel/behaviour proof
written to nail down one specific, now-shipped bugfix. They are kept rather
than deleted per the project's script policy. None of these are wired into
CI or into any firridge; the regression coverage they proved now lives in a
permanent automated test under `tests/`.

Do not restore one of these as an active tool without first checking whether
its sibling `lib_*.py` helper in `scripts/` (several were extracted
specifically to back one of these files: `lib_adopt_clear_server.py`,
`lib_theme_carrier_checks.py`, `lib_sidebar_edge_checks.py`) still matches
the shipped code, and whether its own cross-imports of other archived or
kept scripts still resolve from this new location. They are not maintained
here and are not expected to still run.

| Script | What it verified | Closed by | Covered by |
|---|---|---|---|
| `verify_attribution_prompt.py` | Stage C attribution prompt pixels: layout, positive control, unstyled buttons, zero-pixel card, injected glyph in a rendered name | `bc9fa45d` | `tests/test_session_attribution_prompt_api.py`, `tests/test_home_screen_mechanics.node.mjs` |
| `verify_dead_row_restart.py` | a dead session row offering restart, not only delete | `4d60c4ed` | `tests/test_dead_row_renders_dead.node.mjs`, `tests/test_restart_*` family |
| `verify_ended_session_marking.py` | the ended-session row rendered correctly in both themes | `40cc32d7` | `tests/test_ended_sessions_visibility.node.mjs` |
| `verify_family_pill_tilde.py` | tilde count on a guessed agent-family pill | `73952dd1` | `tests/test_agent_family_pill.node.mjs`, `tests/test_agent_family_display.py` |
| `verify_folder_picker.py` | the folder picker modal still worked after being extracted from launchpad.js | `e7875a70` | `tests/test_folder_picker_modal.node.mjs` |
| `verify_fresh_install.py` | a genuinely empty install has a usable first screen | `845cf005` | `tests/test_fresh_install.py` |
| `verify_login_chrome.py` | the login screen's chrome (kebab icon, header menu) actually gone, in pixels | `29b4341b` | `tests/test_login_chrome.node.mjs`, `tests/test_login_chrome_control_can_fail.py`, `tests/test_csp_no_inline_handlers.node.mjs` |
| `verify_login_theme.py` | the login screen renders in the user's theme, not Claude's | `579fc453` | `tests/test_login_theme_precache.node.mjs` |
| `verify_logout_chrome.py` | clicking logout actually logs the user out (CSP forbids inline handlers) | `b1772f2d` | `tests/test_logout_confirms_once.node.mjs`, `tests/test_csp_no_inline_handlers.node.mjs` |
| `verify_missing_project_click.py` | clicking a project whose folder is gone says so instead of doing nothing | `4002248b` | `tests/test_project_presence.py` |
| `verify_session_name_surfaces.py` | the tab title and a toast card call a session by the name its owner gave it | `08353e38` | `tests/test_session_label_resolver.node.mjs` |
| `verify_session_ownership_badge.py` | the tmux/external ownership badge, adopt-then-owned in both directions | `a2495891` | `tests/test_session_ownership_origin.py` |
| `verify_session_stripe.py` | the session-type left-edge stripe removed, row border themed instead | `ddadd80f` | `tests/test_theme_token_sourcing.py` |
| `verify_session_theme_carrier.py` | the row border means selection only, and theme identity moved off it | `ef9fb16e` | `tests/test_session_theme_tint.node.mjs` |
| `verify_settings_gui.py` | the workspace settings tab actually renders and is reachable, in pixels | `2fbc1f2f` | `tests/test_settings_workspace.node.mjs` |
| `verify_sidebar_row_edges.py` | the thick left colour bar removed from every sidebar row | `f1b7e120` | `tests/test_session_theme_tint.node.mjs`, `tests/test_sidebar_sessions.node.mjs` |
| `verify_status_dot_shape.py` | `unknown` renders as a different shape from every definite status | `b6ad2ae9` | `tests/test_status_led.node.mjs` |
| `verify_toast_dismiss.py` | toasts leave on user action, stay otherwise, scoped correctly | `76d6ea8` | `tests/test_toast_dismiss.node.mjs` |
| `verify_toast_stacking.py` | a burst of toasts stays legible, the cap/overflow row is a real measured box | `fbf35fd6` | `tests/test_toast_stacking.node.mjs` |
| `verify-adopt-resize.py` | an adopted tmux session resizes like any other | `f22ad1e8` | `tests/test_adopt_resize.py` |

## Kept in place, not archived

These matched the `verify_*` naming pattern but were not moved, for the
reasons below. They still live in `scripts/`.

- `verify_header_icons_and_menu.py` - actively invoked (`VERIFIER=`) by
  `scripts/ci/mutate-header-icons-and-menu.sh`.
- `verify_sidebar_groups.py` - actively invoked by
  `scripts/ci/mutate-sidebar-groups.sh`.
- `verify_sidebar_sessions.py` - actively invoked by
  `scripts/ci/mutate-sidebar-sessions.sh`,
  `scripts/ci/mutate-density-menu-placement.sh`, and
  `scripts/ci/mutate-sidebar-groups.sh`.
- `verify_sidebar_rename.py` - imported by `verify_sidebar_groups.py`
  (`from verify_sidebar_rename import measure_inline_rename`), which is
  itself called by CI mutation testing above. A load-bearing dependency of
  an active tool, not a standalone one-off.
- `verify_lifecycle_reconcile.py` - a parameterised operator tool
  (`--db`, `--listing`), not a proof of one closed bug. Runs the lifecycle
  reaper against an arbitrary real `cloude.db` copy.
- `verify_selection_apps.py`, `verify_selection_regressions.py`,
  `verify_selection_scrolled.py` - a parameterised trio (argparse, live
  server plus TOTP) that cross-import each other
  (`verify_selection_scrolled` is the base module the other two import
  from); general terminal-selection regression coverage, not tied to one
  bug, and still listed as reusable release-time harnesses in
  `RELEASE-NOTES.md`.

