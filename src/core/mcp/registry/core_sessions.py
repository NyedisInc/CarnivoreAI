
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
    "session_wait": ("sessions.wait",
                     "Wait up to 50 s until a session reaches a state (idle, blocked, waiting, exited) or prints a plain string; "
                     "a cursor carries on with no output lost."),
    "session_send_and_wait": ("sessions.messages.send_and_wait",
                              "Send a message to an agent session, then wait (up to 50 s) until its turn ends or it stops on a dialog."),
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
    "session_subagents_list": ("sessions.subagents.list", "List the subagents a live session's agent started in its current conversation, with counts."),
    "session_timers_list": ("sessions.timers.list", "List the timers of a live session's current conversation, with counts and open background work."),
    "session_background_jobs_list": ("sessions.background_jobs.list",
                                     "List the tool shells a live Claude session is running: pid, start, command, launching subagent."),
    "session_pane_facts_get": ("sessions.pane.facts.get", "Get a live session's pane facts: folder, foreground command, git branch, size."),
    "session_token_usage_get": ("sessions.tokens.usage.get", "Get one live session's token spend, cost estimate and context headroom."),
    "session_prompts_list": ("sessions.prompts.list", "List the prompts typed into a live Claude session, from its transcript."),
    "session_tasks_list": ("sessions.tasks.list", "List the task list a live Claude session's agent keeps."),
    "session_skill_fires_list": ("sessions.skill_fires.list", "List the newest skill fires of a live session's current conversation."),
    "session_git_diff_get": ("sessions.git.diff.get", "Get one changed file's diff since HEAD in a live session's repository."),
    "session_local_servers_list": ("sessions.local_servers.list", "List the dev servers detected in a live session's output."),
    "session_conversations_list": ("sessions.history.conversations.list",
                                   "List a session's current and earlier conversations, newest first, with summaries."),
    "session_resume_candidates_list": ("sessions.resume_candidates.list", "List stopped sessions on this computer that could be resumed."),
    "session_adoption_candidates_list": ("sessions.adoption_candidates.list",
                                         "List tmux sessions started outside Carnivore that could be adopted."),
    "session_background_agents_list": ("sessions.background_agents.list",
                                       "List Claude background sessions: forks that run with no terminal and no tmux session."),
    "session_attention_get": ("sessions.attention.get", "Get how fresh the status watcher's reading of each session is."),
    "session_restore_offer_get": ("sessions.restore_offer.get", "Get the open reboot restore offer: sessions that were running and are still closed."),
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
