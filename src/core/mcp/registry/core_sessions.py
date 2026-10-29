
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "sessions_list": ("sessions.list",
                      "List live sessions on this computer and paired ones (host column), optionally asleep ones too; 50 rows "
                      "by default, up to 200."),
    "session_status": ("sessions.status.get", "Get one session's status detail, live or asleep (an asleep one answers asleep: true)."),
    "session_read_output": ("sessions.output.get",
                            "Read the tail of a session's terminal output: up to 500 lines, ANSI stripped, secrets redacted."),
    "session_create": ("sessions.create",
                       "Create (start) a new Claude or Codex session in a folder or project, here or on a paired computer. "
                       "Limits: 5 live per agent, 20 in all."),
    "session_restart": ("sessions.restart",
                        "Restart a session's agent as a resume of its conversation; also wakes an asleep or exited one."),
    "session_folder_move": ("sessions.folder.move",
                            "Move a session out of its temporary folder into a project or a new folder on this computer, resumed "
                            "there in the same conversation."),
    "session_stop": ("sessions.stop", "Stop a session: put it to sleep, keeping its row and conversation for a later wake."),
    "session_wake": ("sessions.wake",
                     "Wake an asleep session (by session_uuid or tmux name) so it resumes the same conversation."),
    "session_interrupt": ("sessions.interrupt", "Interrupt a live agent session by pressing Escape once."),
    "session_delete": ("sessions.delete",
                       "Delete a session: kill its tmux session, or drop an asleep one from the lists. Always waits for the "
                       "owner's approval."),
    "session_purge": ("sessions.purge",
                      "Purge a stopped session for good: its record and everything traced to it, transcripts included. Plan "
                      "first; the owner types the name to approve."),
    "session_send_message": ("sessions.messages.send",
                             "Send a message to an agent session's prompt and submit it. Refused while a dialog is open."),
    "session_send_keys": ("sessions.keys.send", "Send keys to a session: type text and press named keys (Enter, Escape, arrows)."),
    "agent_spawn": ("sessions.agents.spawn",
                    "Spawn a visible Claude or Codex agent with a task assigned through crosstalk, here or on a paired "
                    "computer, and receive its completion reply."),
    "session_dialog_get": ("sessions.dialogs.get",
                           "Get the dialog open on a live session (permission prompt, question, form): kind, options and the "
                           "fingerprint an answer needs."),
    "session_dialog_answer": ("sessions.dialogs.answer",
                              "Answer a session's open dialog with one choice, using the fingerprint from session_dialog_get."),
    "session_dialog_questions_answer": ("sessions.dialogs.questions.answer",
                                        "Answer every question of a session's open AskUserQuestion in one call and submit "
                                        "once. Always waits for the owner's approval."),
    "session_notes_get": ("sessions.notes.get", "Get one session's markdown note (redacted) and its revision, live or asleep."),
    "session_notes_put": ("sessions.notes.set",
                          "Set (replace) a session's markdown note; send the revision session_notes_get returned."),
    "session_description_set": ("sessions.description.set",
                                "Set a session's short and/or long description so other agents know what it is doing."),
    "session_rename": ("sessions.label.set",
                       "Set a session's label (what the drawer shows), live or asleep; the tmux name never changes."),
    "session_theme_set": ("sessions.theme.set", "Set or clear a theme pin on one session (theme_id from themes_list)."),
    "session_unread_set": ("sessions.unread.set", "Mark one session unread for follow-up, or read, on every device."),
    "session_notifications_set": ("sessions.notifications.set", "Mute or unmute one session's notifications, live or asleep."),
    "session_shell_get": ("sessions.shell.get",
                          "Get the companion shell of a live agent on this computer (id, tmux name, pane state); never "
                          "creates one."),
    "session_shell_open": ("sessions.shell.open",
                           "Open a live agent's companion shell: a plain terminal in its folder, created on first use, "
                           "hidden from session lists."),
    "session_git_status": ("sessions.git.status.get",
                           "Get git status of a session's repository: branch, ahead/behind, changed files since HEAD."),
    "session_attach_command": ("sessions.attach.command.get",
                               "Get the argv that attaches a terminal to a local session: tmux, socket, attach-session, "
                               "=<name>. Launches nothing."),
    "session_lineage_get": ("sessions.history.lineage.get",
                            "Get a session's conversation lineage, oldest first: how each began (clear, fork, rewind), "
                            "split points, milestones."),
    "session_timeline_get": ("sessions.history.timeline.get",
                             "Get a session's timeline: conversations as bars with splits, compacts, bookmarks, restarts "
                             "and sleeps."),
    "session_mcp_reconnect": ("sessions.mcp.reconnect",
                              "Reconnect the MCP servers an idle claude session lost (types /mcp reconnect); busy "
                              "sessions are refused."),
    "bookmarks_list": ("sessions.bookmarks.list", "List a session's bookmarks, newest first: id, label, author, the prompt it marks."),
    "bookmark_add": ("sessions.bookmarks.add",
                     "Add a bookmark where a Claude Code conversation stands now, with a label, before a risky change."),
    "bookmark_branch": ("sessions.bookmarks.branch",
                        "Branch a new session from a copy of the conversation cut at a bookmark; the original is untouched."),
    "bookmark_rewind": ("sessions.bookmarks.rewind",
                        "Rewind a session in place to a bookmark: kill its pane and resume a copy cut there. Needs confirm."),
    "launch_profiles_list": ("sessions.launch.profiles.list",
                             "List launch profiles: label, harness, account, model and permissions, with each harness's "
                             "default."),
    "launch_accounts_list": ("sessions.launch.accounts.list",
                             "List the claude accounts session_create can launch on, and the default one."),
    "agents_lookup": ("crosstalk.agents.lookup",
                      "Look up agents by name (\"@Cv-Misc UI\") on this computer and paired ones: id, provider, model, host, "
                      "project, status; view roster lists sessions with descriptions and family."),
    "crosstalk_send": ("crosstalk.send",
                       "Send a durable peer message to another agent by handle or id; wakes an asleep one. The receipt says "
                       "delivered, queued or stuck."),
    "crosstalk_reply": ("crosstalk.reply", "Reply to one crosstalk message addressed to your current pane."),
    "crosstalk_wait": ("crosstalk.wait", "Wait up to 45 seconds for a crosstalk reply or thread message."),
    "crosstalk_inbox": ("crosstalk.inbox.list", "List your own crosstalk messages, newest first, with idle-watch notices."),
    "crosstalk_thread": ("crosstalk.threads.get", "Get a crosstalk thread you take part in, oldest first; page back with before."),
    "crosstalk_threads_list": ("crosstalk.threads.list",
                               "List your past crosstalk threads, newest first; filter by session or project."),
}
