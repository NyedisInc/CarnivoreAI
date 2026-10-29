
from __future__ import annotations

from typing import Mapping, Tuple

TABLE: Mapping[str, Tuple[str, str]] = {
    "task_manager_boards_list": ("task_manager.boards.list",
                                 "List review boards (mockups under review): slug, title, task, revisions, rounds and state "
                                 "(your_turn, with_claude, undelivered, closed); filter by task, state, project."),
    "task_manager_board_get": ("task_manager.boards.get",
                               "Read one review board: revisions with prompts, the owner's rounds and notes, saves, the live draft "
                               "and its sends. Never returns HTML."),
    "task_manager_board_create": ("task_manager.boards.create",
                                  "Create a review board for a task: post revision r1 (page, summary, prompts) the owner reviews in "
                                  "rounds; his send comes back on the task."),
    "task_manager_board_revision_add": ("task_manager.boards.revisions.add",
                                        "Add the next revision to a review board (new page, summary, prompts), optionally answering "
                                        "one of the owner's rounds. Older revisions never change."),
    "task_manager_board_focus": ("task_manager.boards.focus",
                                 "Open a review board on the owner's screen at a revision (default newest) to point him at it. "
                                 "Screen only."),
    "task_manager_board_attachment_add": ("task_manager.boards.attachments.add",
                                          "Attach files (spec, PDF, screenshot, notes) to a review board's task, inline base64 or, "
                                          "from a local pane, by path. At most 10 files."),
    "task_manager_board_attachment_remove": ("task_manager.boards.attachments.remove",
                                             "Take an attachment off a review board (a removed entry stays in its index). The file stays on the "
                                             "task and its thread still links it."),
    "task_manager_board_live_set": ("task_manager.boards.live.set",
                                    "Run a review board as a live session: each call overwrites the working draft the owner sees "
                                    "update in place; starts the session on the first call."),
    "task_manager_board_live_stop": ("task_manager.boards.live.stop",
                                     "End a review board's live session: drop the working draft (freeze a milestone first to keep "
                                     "it) and send the task to review."),
    "task_manager_board_milestone_add": ("task_manager.boards.milestones.add",
                                         "Bookmark a live board's working draft as a named revision, like a git commit, when the "
                                         "owner says bookmark that."),
    "task_manager_scratch_post": ("task_manager.scratch.post",
                                  "Post a page and its files to a scratch board (a temporary review board) as one revision; the "
                                  "first post creates the board and its Scratch task. Runs at once."),
    "task_manager_scratch_clear": ("task_manager.scratch.clear",
                                   "Ask the owner to clear a scratch board for good (folder, pages, files). Always waits for his "
                                   "approval; the Scratch task stays."),
}
