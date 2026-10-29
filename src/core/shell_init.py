"""The one place that decides how ``~/.zshrc`` is sourced for a new pane.

WHY THIS MODULE EXISTS
----------------------

Every agent launch is wrapped in ``zsh -c 'source ~/.zshrc ...; <cmd>'``.
The rc has to be sourced in the launching shell itself, because that is
where the user's ``PATH``, exports and shell FUNCTIONS come from - ``keyc``
is a function defined in ``~/.zshrc``, and tmux's spawned pane shell is
neither interactive nor a login shell, so without the source a launch is
"command not found". That requirement is not negotiable and nothing here
changes it.

THE BUG THIS FIXES: A SILENT HANG AT SESSION START
--------------------------------------------------

But rc ran with a TTY still on **stdin**, and a script that sees a TTY on
stdin reasonably concludes it may ask the user a question. The reported
case was a dotfiles update checker whose logic is, correctly::

In a tmux pane ``[[ -t 0 ]]`` is true, so it prompts and blocks on
``read``. The prompt goes to **stdout** (``printf``, not ``>&2``), which
``>/dev/null`` throws away. Result: the pane emits zero bytes,
``capture-pane`` returns completely empty, the client faithfully renders
nothing, and the session looks dead. The user presses Enter blind and
that keystroke answers a question they never saw.

So the app was handing rc a TTY on stdin while discarding its stdout: it
invited the question and then hid it.

THE FIX, AND WHAT WAS REJECTED
------------------------------

The prefix is now ``source ~/.zshrc >/dev/null 2>&1 </dev/null``. The
redirections apply to the ``source`` builtin ONLY - fd 0 is restored for
every command after it, so the AGENT still gets the pane's real TTY on
stdin, which it needs. Verified in a real detached tmux session: after
the source, ``[[ -t 0 ]]`` is true, ``$FROM_RC`` is exported, and a
function defined by the rc still runs.

Making stdin consistent with stdout is what fixes the class:

* A script that gates on ``[[ -t 0 ]]`` - the near-universal convention,
  and exactly what the reported script does - now takes its
  non-interactive branch and never blocks. That branch already exists
  because the author wrote it for SSH and cron; a pane whose output is
  discarded is the same situation.
* A script that reads WITHOUT a guard gets EOF immediately: ``read``
  returns non-zero with an empty REPLY and the script carries on. An
  unbounded hang becomes an instant default. Verified in tmux.

Rejected alternatives:
"""

from __future__ import annotations

import shlex

RC_SOURCE = "source ~/.zshrc >/dev/null 2>&1 </dev/null"


def rc_prefixed(command: str) -> str:
    return f"zsh -c {shlex.quote(f'{RC_SOURCE}; {command}')}"
