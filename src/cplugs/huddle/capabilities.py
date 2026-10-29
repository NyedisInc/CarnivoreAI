
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "task_manager_guide": ("task_manager.guide.get",
                           "Read the Task Manager (huddle) rules before a write: core rules and an index, one topic, the whole "
                           "guide, or only what changed since a guide_rev."),
    "task_manager_tasks_list": ("task_manager.tasks.list",
                                "List a Task Manager list's tasks as lean rows (id, title, status, group, unread), or one task in "
                                "full with its latest messages; page with cursor."),
    "task_manager_schedules_list": ("task_manager.schedules.list",
                                    "List scheduled tasks across every list, soonest next fire first, with repeat, paused state "
                                    "and who gets pinged. Read only."),
    "task_manager_changes": ("task_manager.tasks.changes.list",
                             "List what changed in the Task Manager after a cursor: changed tasks and new messages, the "
                             "owner's in full, your own left out by default."),
    "task_manager_add": ("task_manager.tasks.create",
                         "Create a task on a Task Manager list, marked as yours: plain text, a short title, a group, optionally "
                         "a schedule (fire_at)."),
    "task_manager_update": ("task_manager.tasks.update",
                            "Update a task: text, title or state (working when you start, waiting when blocked, review when "
                            "finished with a review block). Only the owner approves."),
    "task_manager_state_request": ("task_manager.tasks.state.request",
                                   "Ask the owner to reopen an approved task, close an unapproved one, undo a closure, or delete one for good; "
                                   "waits for his approval card."),
    "task_manager_ask": ("task_manager.tasks.ask",
                         "Ask the owner a question on a task only when blocked on his answer: typed questions (yes_no, single, "
                         "multi, rank, text) with context; he is notified."),
    "task_manager_reply": ("task_manager.tasks.reply",
                           "Reply on a task's thread: an info (fyi) or an answer to the owner's question (with quote). Pipe "
                           "tables and files allowed."),
    "task_manager_move": ("task_manager.tasks.move",
                          "Move a task to another Task Manager list and/or into a group; its thread, state and unread flag go "
                          "with it."),
    "task_manager_role_set": ("task_manager.roles.set",
                              "Set a role on your own session: dnd (no new tasks reach you) or lead (take your project's "
                              "vacant lead seat)."),
    "task_manager_group_create": ("task_manager.groups.create",
                                  "Create a named group (a foldable area section) on a Task Manager list; an existing name "
                                  "answers that group, so repeating is safe."),
    "task_manager_group_update": ("task_manager.groups.update",
                                  "Rename, reorder or remove a Task Manager group; removing ungroups its tasks, never deletes "
                                  "them."),
    "task_manager_answered_set": ("task_manager.tasks.answered.set",
                                  "Mark a task's open question answered without a reply, only when the owner answered it "
                                  "outside the Task Manager."),
    "task_manager_fork": ("task_manager.tasks.fork",
                          "Fork a task: a new task beside it with its own state, optionally a new state for the original, in "
                          "one transaction."),
    "task_manager_batch_run": ("task_manager.tasks.batch.run",
                               "Run many Task Manager edits on one list in one call (add, update, reply, ask, move, fork, "
                               "progress...), in order, a lean answer per op."),
    "task_manager_artifact_add": ("task_manager.tasks.artifacts.add",
                                  "Show the owner a page on a task: one self-contained HTML document (mock-up, chart, "
                                  "comparison) posted as a card, max 2 MB. Not for text."),
    "task_manager_entries_list": ("task_manager.entries.list",
                                  "List the owner's add-box entries still waiting to be filed, with their raw text. Read "
                                  "only."),
    "task_manager_entry_import": ("task_manager.entries.import",
                                  "File an add-box entry as one or more tasks: split requests, title and group each, set state "
                                  "per his words."),
    "task_manager_progress_set": ("task_manager.tasks.progress.set",
                                  "Show a worker's live phase (queued, running, testing, blocked, done) and a short note on a "
                                  "working task's row."),
    "task_manager_file_remove": ("task_manager.tasks.files.remove",
                                 "Delete one file you attached to a task: the thread says it was removed and its bytes go, unless "
                                 "another task names them. The owner or the attaching agent only."),
    "task_manager_wait_update": ("task_manager.tasks.wait.update",
                                 "End a waiting task's wait as cleared or failed (with a reason); the task goes back to open."),
    "huddle_focus": ("task_manager.tasks.focus",
                     "Deprecated: highlight tasks and open one in the owner's views. Use the marker argument of "
                     "task_manager_update instead."),
    "task_manager_leads_list": ("task_manager.leads.list",
                                "Preview the lead retrofit per project: which lead session would become the Swarm project or "
                                "company agent, or why it is skipped. Read only."),
    "task_manager_leads_update": ("task_manager.leads.update",
                                  "Promote each project's lead session into its Swarm project agent, keeping its conversation. "
                                  "Always waits for the owner's approval."),
    "task_manager_lead_set": ("task_manager.leads.set",
                              "Set a project's lead session (re-point or promote its Swarm agent, or pin only the seat). "
                              "Always waits for the owner's approval."),
}
