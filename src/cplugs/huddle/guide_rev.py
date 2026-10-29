
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Dict, List, Mapping, NamedTuple, Tuple

from src.cplugs.huddle import guide_sections

TASK_MANAGER_GUIDE_REV = 109


class Change(NamedTuple):

    rev: int
    summary: str
    agent_facing: bool = True


TASK_MANAGER_GUIDE_CHANGELOG: Tuple[Change, ...] = (
    Change(1, "First numbered revision: guide_rev rides every huddle answer."),
    Change(2, "The rules ship in the app and come from huddle_guide (the skill is optional). Section 4: call huddle_guide before "
        "your first huddle write; since_rev answers what changed. Section 14: a yes_no recommend.value is a boolean "
        "(true or false), never the text yes or no."),
    Change(3, "Section 16: a personal add-on skill declares `extends: huddle` and `guide_rev` in its front matter; an answer's "
        "stale_extensions lists add-ons written for an older rev, so check each for conflicts and then raise its guide_rev."),
    Change(4, "Section 17: flag an item with flag_color (purple, pink, teal, lime; status colors refused) and a short flag_reason on "
        "huddle_update, huddle_reply, huddle_focus or a batch op, to group what the owner should see together, never to mimic a "
        "status; flag_color \"\" clears it, approving or deleting clears it."),
    Change(5, "Naming only: the feature the rules call the pack is now called the swarm and its top agent SysOp; the pack_* tool names, "
        "list keys and every rule are unchanged.", agent_facing=False),
    Change(6, "Section 18: cards: four columns, swarm_card_* for Swarm agents, held cards refuse huddle state, move and delete writes."),
    Change(7, "Section 10: pass huddle_item on every call that waits for the owner's approval; it shows on that item with approve and "
        "deny (none: the list's \"claude's approvals\" item), approvals never expire, and the outcome comes back as a post on the "
        "item and a tell. A read look never lands an item in needs you."),
    Change(8, "Section 37: Carnivore answers the development-channels warning itself at its own launches; no rule for agents changes.", agent_facing=False),
    Change(9, "Section 35: markdown renders on every huddle surface, folds cut parsed text, one bubble base.", agent_facing=False),
    Change(10, "Section 51 (docs/task-manager.md): the owner's third list view, carnivore's view, groups the list by your flags (one group per "
        "color and reason, then everything else), so a flag_reason is a group name there; no action needed.", agent_facing=False),
    Change(11, "New read tool huddle_schedules (docs/task-manager.md section 7): every scheduled item across all lists, soonest next fire "
         "first, with list and paused filters; call it before you schedule or pause something."),
    Change(12, "Naming only: huddle_schedules is now huddle_schedules_list (one MCP naming scheme, docs/mcp-server.md \"Tool names\"); "
         "same arguments and answer."),
    Change(13, "Section 19: only a question, a look with an action, or a review reaches the owner; a question-like info or answer is "
         "refused (override not_a_question), a plain ask with 2+ ? needs questions, and every write answer carries reaches_owner "
         "and reaches_owner_reason."),
    Change(14, "Section 20: write to your own project's list (list: mine); another project's list is refused unless the call passes "
         "cross_project: true, and the owner sees it as cross-project."),
    Change(15, "Section 53: an item you write onto another project's list (cross_project: true) is tagged from_project {id, name} "
         "and the owner's row reads \"from <project>\"; no action needed.", agent_facing=False),
    Change(16, "Naming only: the agent tree is the swarm everywhere (docs/swarm.md, "
         "/api/v1/swarm); no behavior changed. Pack now means the group of paired computers.", agent_facing=False),
    Change(17, "Section 54 (skill section 21): a project may have the nudge on; a quiet open or working item gets a tell starting "
         "\"huddle nudge:\". Answer on the item: huddle_progress, done_by_claude or waiting_install, huddle_ask, or open."),
    Change(18, "Section 55: the owner's screen no longer shows a waiting-to-send section or held tell strips; nothing changes for agents, "
         "the tell and the item statuses are as before.", agent_facing=False),
    Change(19, "Section 56: the owner's screen shows a working item's session checklist as a steps strip beside your progress lines; "
         "nothing changes for agents, keep your TodoWrite list current.", agent_facing=False),
    Change(20, "Section 54 (skill section 21): a nudge now names ONE item. An open item nobody claimed, or an idle session with no claimed item "
         "told to pick up the next open one, starts \"huddle nudge:\" too; claim it with huddle_update state working, or ask."),
    Change(21, "Section 57 (skill sections 13 and 14): a fenced code block draws as a command area with a copy button, and a single "
         "typed question takes command {text, lang?} (or a string): a copyable command above options that draw as pills, so a handoff "
         "needs no trip out of the sidebar. The stored answer is unchanged."),
    Change(22, "Section 10: approvals are no longer shown in the huddle (no \"claude's approvals\" item, row, post or tell); huddle_item is gone "
         "from the tool schemas and ignored if passed, so read an approval's outcome with approval_wait."),
    Change(23, "Section 58: the owner may dismiss a question with a shift-click: every question comes back skipped:true (dismissed:true) and the "
         "answer text reads dismissed, required ones included; treat it as no answer wanted, not as a failure."),
    Change(24, "Section 5, 9 and 19: the look is retired. huddle_reply kind attention and action tick, push or answer are refused (use huddle_ask, or huddle_update done_by_claude with review_action); a bare attention or action read or none becomes an info with notify true; an omitted kind is an info; notify true on an info marks it unread and badges the tab, asking nothing."),
    Change(25, "Section 22 (docs/task-manager.md section 60): the owner's add box queues their raw text; a tell starting \"huddle inbox:\" names an entry id. File it with huddle_inbox_file (huddle_inbox_list reads pending ones): split several asks into several items, title and group each, obey a leading backlog (back_burner), now (working) or ask (question). Never recreate it with huddle_add."),
    Change(26, "Section 23 (docs/task-manager.md section 61): to SHOW the owner a visual, preview or comparison, post huddle_artifact {item, title, description, html or file_path}: one self-contained HTML page up to 2 MB shown as a card; it runs with no network and cannot answer back, so follow it with huddle_ask for any question. Marks the item unread."),
    Change(27, "docs/task-manager.md section 62: carnivore's view is hidden behind a flag (a stored claude view reads as by group) and the owner can turn on a project accordion; nothing changes in how agents write.", agent_facing=False),
    Change(28, "docs/task-manager.md section 63: huddle_add and huddle_update take an optional github_issue, a full https://github.com/<owner>/<repo>/issues/<number> URL (empty string clears it); set it when an item tracks a CarnivoreAI issue. Items return github_issue only when set."),
    Change(29, "docs/task-manager.md section 54: the nudge also covers an idle agent holding a waiting_install item; its tell says to install it, check it on the live page, then set done_by_claude with a review, or huddle_ask if blocked."),
    Change(30, "docs/task-manager.md section 65: every answer can carry your_items (up to 5 {id, title, state, age_min}) and your_items_more: what you hold working or waiting_install; finish, install and hand over each."),
    Change(31, "docs/task-manager.md section 66: the owner's plain changes (ticks, replies, adds) are batched into ONE tell after a few quiet seconds (30 at most); its since-cursor is the oldest change you have not read, so one huddle_changes read covers all. An answer to your question still arrives at once."),
    Change(32, "docs/task-manager.md section 67: each guarded write is logged with the acting session and a cross-project item stores its source item; no tool contract change.", agent_facing=False),
    Change(33, "docs/task-manager.md section 54: a nudge says why you hold each working item (you set it, or you picked up its tell and have not replied); no tool contract change.", agent_facing=False),
    Change(34, "Skill section 25 (docs/task-manager.md section 68): the session that holds an item working owns its tells: the owner's changes to that item are told to you, even after done_by_claude or waiting_install, naming the item ids; huddle_list rows carry owned_by. The owner's tick or a delete ends it; a read never takes it over."),
    Change(35, "Section 66: queued tells survive a restart (untold lists are re-queued at start), and the tell claude press covers only lists with untold changes.", agent_facing=False),
    Change(36, "Section 69: HTTP only. GET /cplugs/huddle/aggregate sends slim threads (?threads=1 for whole ones) and GET /cplugs/huddle/items/{id} reads one whole thread; the MCP tools are unchanged.", agent_facing=False),
    Change(37, "HTTP only. POST /cplugs/huddle/groups/fold folds many groups in one write (the owner's Shift+click on a header); no tool contract change.", agent_facing=False),
    Change(38, "The nudge is its own plugin (nudge, off by default: no nudge text is posted until the owner turns it on; its minutes, tries and texts are its settings); the row menu no longer has the swarm nudge entry; no tool contract change (docs/task-manager.md section 54).", agent_facing=False),
    Change(39, "The owner's plain chat reply on an item answers its newest open typed question provisionally: the question is answered, the item moves to working, and you read their reply with answers_to and freeform true (no answers); ask a new question if you still need something (skill section 14, docs/task-manager.md typed asks)."),
    Change(40, "HTTP and UI only. The review card shows a one-line summary, the description in a fold, then what to review and where; docs/task-manager.md section 23; no tool contract change.", agent_facing=False),
    Change(41, "Skill section 5 (docs/task-manager.md section 23): huddle_update, huddle_add and huddle_fork take an optional review_summary, one plain line (300 characters at most) that the owner's review card shows above the folded description; set it when review_description runs past a line or two."),
    Change(42, "Docs/huddle.md section 66: the owner's answers to your questions are batched with their other changes (one tell after 10 quiet seconds, 45 at most) instead of arriving at once; read them with huddle_changes as before."),
    Change(43, "Skill section 26 (docs/task-manager.md section 70): huddle_update still refuses an approved item and its error now names huddle_item_state_request {item, action: reopen | close, reason, to_state?}: every request waits for the owner in the approvals inbox (one card per item, a repeat updates the reason), nothing changes until the owner approves, a close ends approved (their approve is the tick), and the outcome is a line on the item; read it with approval_wait."),
    Change(44, "Docs/huddle.md typed asks: the owner's chat reply that provisionally answers your open question now hands the item back to you as working, so read it with huddle_changes and ask again if needed; no tool contract change."),
    Change(45, "Task Manager (docs/task-manager.md section 2): approved and approved_with_note are one stored state, done (a note on it says read the note); the old names still work on input and every answer says done."),
    Change(46, "Task Manager (skill section 3, docs/task-manager.md section 2): waiting_install is now waiting (an install, a reboot or a person you wait on); huddle_update state waiting_install still works and every answer says waiting."),
    Change(47, "Task Manager (skill section 3, docs/task-manager.md section 29): back_burner is now todo (wanted, not today); huddle_update state back_burner and the add-box backlog still work and every answer says todo."),
    Change(48, "Task Manager (skill sections 3 and 4, docs/task-manager.md section 2): done_by_claude is now review (Claude says it is done, you look); huddle_update state done_by_claude still works, every answer says review, and the list summary counts it as review."),
    Change(49, "Task Manager (docs/task-manager.md section 72): every item carries lane (task_manager or swarm); the swarm never ticks or deletes a task_manager item. Additive, no tool contract change.", agent_facing=False),
    Change(50, "Task Manager (docs/task-manager.md section 72): huddle_add and huddle_update take an optional perceived_ask (one line: what you understood the owner to want); the item text stays the description; a task you add while you hold another working links that one's original add box entry (from_inbox)."),
    Change(51, "Task Manager (docs/task-manager.md section 72): every item dict carries blockers (its uncleared ones) while it has any; recording and clearing them is not a tool yet, and nothing blocks a move yet.", agent_facing=False),
    Change(52, "Task Manager (docs/task-manager.md section 72): every stored-state move is now recorded (item_lineage) and readable at GET /cplugs/huddle/items/{id}/lineage; no tool contract change.", agent_facing=False),
    Change(53, "Filing section: huddle_inbox_file takes perceived_ask on each item; give every filed item one line of what you understood the owner to want."),
    Change(54, "Docs/huddle.md section 60: an item's from_inbox gains direct (true when it was filed from that add-box entry itself, false when it only carries the link); the app shows the owner's icon on a direct item. The answer form loses its Shift hold (section 36) and the multiline add box uses the one-line placeholder; a folded heading's marks skip items hide completed hides (section 64); no tool contract change.", agent_facing=False),
    Change(55, "HTTP and UI only (docs/task-manager.md section 64 and the hide completed read): a folded heading's marks skip items hide completed hides; with hide completed on the app's list reads send completed items as placeholders (?hide_completed=1); no tool contract change.", agent_facing=False),
    Change(56, "HTTP and UI only (docs/task-manager.md section 56): GET /cplugs/huddle/steps no longer answers a sessions array and a working session that claims no item shows no steps line under its project; a claimed working item keeps its strip; no tool contract change.", agent_facing=False),
    Change(57, "Section 27: huddle_add takes state (open or todo); your move past an uncleared blocker stops in waiting and the history says so; you may park an item freely."),
    Change(58, "Section 27: one open question per item; a new huddle_ask folds the older one, marked superseded; the owner's answer, submit or cancel sends the item to open."),
    Change(59, "Section 27: the owner's reply on a review or done item does not move it; answer a question with huddle_reply, or send huddle_reply changes true to send it to open."),
    Change(60, "Section 27: huddle_delete and the batch delete op are refused for agents; ask with huddle_item_state_request action delete (a hard delete the owner approves in the inbox)."),
    Change(61, "Section 27: unticking goes to open; ticking a repeating task returns it to scheduled, not done; a schedule firing on a waiting item is skipped and logged."),
    Change(62, "Skill sections 6 and 25 (docs/task-manager.md section 13, #1723): reading an item never makes it working, told or not; only your huddle_update state working claims it, so claim before you start. Your claims end when you /clear or start a new conversation; an item you only read stays open."),
    Change(63, "Skill section 28 (docs/task-manager.md section 74): review boards. When a mockup needs rounds of the owner's review, use "
         "task_manager_board_create / _revise (and _list / _get to read their rounds) instead of huddle_artifact; a revision posts a "
         "card on the task and by default puts it in review; name the round you answer with answers_round."),
    Change(64, "Section 27 (reverses rev 59): the owner's reply on a review or done item moves it to open at once; answer a question with huddle_reply, then return the item with huddle_update state review (state done for a task the owner had ticked: allowed once, only after you answered their reply); for changes, work them. huddle_reply changes is a no-op; huddle_changes names the replied items in owner_replied."),
    Change(65, "Skill section 29 (docs/task-manager.md section 76): huddle_role_set {role: lead | dnd, on} sets a role on YOUR OWN session (lead only while the seat is vacant; a held seat is refused, ask the owner; do not disturb stops new tasks reaching you); huddle_list on a project carries roles; any move of a task out of open ends your claim; a swarm-lane task cannot be claimed with huddle_update working."),
    Change(66, "Skill section 21 (docs/task-manager.md section 76.3): the nudge is on for every project unless switched off, never fires on a waiting task, and counts a task as stalled only when the session that owns it is idle past the timeout; a still-silent task becomes ONE question from Carnivore (unstick, park or cancel, category stall, author_key carnivore) that is the owner's to answer, with no toast; park moves the task to todo, unstick and cancel leave it open and you decide on your next send."),
    Change(67, "Skill section 29 (docs/task-manager.md section 76.4): huddle_update and a huddle_batch update op take tag (me, an agents_lookup id, or empty to clear): a tagged task is sent to its agent first, waking it if asleep, as a normal send; a gone agent hands it to the project lead, else the owner is asked; the tag survives the owner's tick; unstick on a stall question sends one tell to the owning session, waking it."),
    Change(68, "Skill section 28 (docs/reviewboard.md, slice 4): new tool task_manager_board_focus {board, revision?} puts a review board on the owner's screen "
         "(a row in their browser list, shown in the center screen); use it to point the owner at a revision you just posted."),
    Change(69, "Skill section 28 and docs/task-manager.md section 74 (docs/reviewboard.md, slice 5): the owner's review round arrives as their reply on the task "
         "(picks, checks, notes, ending in a read-it line); task_manager_board_get since_round N returns the rounds after N."),
    Change(70, "docs/task-manager.md section 77: with the Task Manager folder set, an attached file, an artifact page and a new board are saved under "
         "<root>/<project>/<task>/ (pastes, artifacts, boards); a file's path in a read is still absolute, so read it as before.", agent_facing=False),
    Change(71, "Skill section 22 (docs/task-manager.md section 78): the add box sends a multi-line paste as ONE inbox entry and tells the project lead, else the "
         "most recently active session; split it into tasks yourself. An entry nobody files in about two minutes stays queued and the owner is asked "
         "(file it himself, start a session, wait): file promptly, a late huddle_inbox_file on a stuck entry still works."),
    Change(72, "Skill section 30 (docs/task-manager.md section 80): huddle_reply takes offer_schedule {when, title}; the owner accepts with one click and "
         "then tells you to file it: call huddle_add with fire_at and reply with the date. A tell now names the task and message of an owner reply: "
         "read that thread with huddle_list item=<id>. docs/task-manager.md section 79: the owner picks which statuses the Task Manager key's badge counts."),
    Change(73, "Skill section 31 (docs/task-manager.md section 81): huddle_update state waiting REQUIRES waiting_on and wait_kind (install, session, person, vendor, other) and expect_by or the kind's default "
         "(install 1h, session 3h, person and vendor 24h; other none); waiting on the owner is refused, ask with huddle_ask. When the time plus half again passes the task comes back to you open with a "
         "challenge: clear it, extend once (state waiting again with extend_reason), or ask the owner; a second lapse asks the owner. Optional wait_check from a fixed menu clears it by itself; the park answer's "
         "wait_callback.token (shown once) lets a script POST /cplugs/huddle/items/<id>/wait/resolve {token, result: cleared|failed}, or call huddle_wait_update."),
    Change(74, "Skill section 4 (#1757): huddle_guide is only needed before a write other than huddle_progress and huddle_reply; with no arguments it answers the core "
               "sections plus an index (topic: <number or name> returns one, detail: true all) and no changelog; since_rev answers up_to_date when nothing above it concerns agents. "
               "huddle_changes sends no threads unless detail: true; huddle_list item sends the last 10 messages plus thread_more unless detail: true; typed questions are section 32."),
    Change(75, "docs/task-manager.md section 83: huddle_reply takes file_paths, up to 10 ABSOLUTE paths on this computer (a session running here only, "
               "refused for a token); each file is copied into the task's folder and shows on the thread like the owner's pasted files (an image up "
               "to 10 MB, any other file 50 MB). For a page plus images the owner reads, task_manager_scratch_post posts to a scratch board with no approval."),
    Change(76, "Section 84 (docs/task-manager.md): four tool names changed to fit the naming scheme: huddle_wait_resolve is huddle_wait_update, task_manager_board_list is "
        "task_manager_boards_list, task_manager_board_revise is task_manager_board_revision_add, task_manager_board_open is task_manager_board_focus. A scheduled "
        "task goes to the agent it is tagged to first. If the owner replied on a review or done task and your turn ends without an answer, Carnivore returns it."),
    Change(77, "Section 85 (docs/task-manager.md): a one-time schedule skipped while its task was waiting, on the owner's turn or on the back burner now fires at the next pass "
        "once the task leaves that state. You cannot park a task waiting while its pending one-time fire_at is before the wait's expect_by (nor set such a fire_at on a waiting task): "
        "set expect_by before the fire, add a wait_check, or move fire_at. huddle_schedules_list with list all (or omitted) returns every list."),
    Change(78, "Section 29 (docs/task-manager.md section 87, #1789): the project lead IS the Swarm project agent (the old step-aside is gone); an asleep lead is woken by a tell; a lead "
               "cannot go on do not disturb (huddle_role_set dnd is refused for it) and taking the seat clears it; a gone (archived or deleted) lead moves the seat to the company agent, "
               "else SysOp, and the owner picks a new one. New owner-approved tools huddle_lead_set and huddle_leads_update, and the read-only huddle_leads_list."),
    Change(79, "Section 32 (typed questions, #1797): a huddle_ask whose question carries a command (the handoff card with its ran it / failed pills) must hold that one question only; "
               "tapping a pill answers and sends the whole form, so a form mixing a command question with any other question is refused. Ask the rest in a separate huddle_ask."),
    Change(80, "Section 29 (docs/task-manager.md section 87): a company's HQ project is led by the COMPANY agent. huddle_lead_set with agent true on an HQ project, and the "
               "huddle_leads_update plan row promote_company, promote the session into the company agent, keeping its conversation."),
    Change(81, "Section 29 (docs/task-manager.md section 87): a project whose folder sits inside another project's folder (Harbor Docker inside Harbor) may be led by the Swarm project agent "
               "of the nearest enclosing project that has one: huddle_lead_set accepts that agent for it, and the seat is held, not gone. Any other project's agent is still refused."),
    Change(82, "Sections 21 and 29 (docs/task-manager.md section 76.5, #1803): a list has no item cap. A task whose owning or claiming session is archived or deleted goes to the "
               "project lead (lineage detail session_gone), else Carnivore asks the owner (owner_gone or owner_wake_failed); the nudge no longer skips a dead session's quiet open task, it routes it the same way and never nudges a waiting task."),
    Change(83, "Sections 27 and 31 (docs/task-manager.md section 89, #1802): a task can wait on its forks. huddle_fork parent_waits true, or huddle_update state waiting with "
               "wait_kind children, holds it in waiting until no fork is open or waiting; your other moves of it stay waiting and the answer says blocked. Carnivore "
               "clears it when the last fork finishes (open, 'cleared: its forked tasks are done'); huddle_wait_update clears it by hand. A park and a fork wait never share a task."),
    Change(84, "Section 29 (docs/task-manager.md section 87): huddle_lead_set takes seat_only true: it pins the Task Manager lead seat to a live or asleep session of the "
               "project and leaves the Swarm project agent alone. That session leads for the Task Manager's routing while it stands; the agent never overrides it. "
               "huddle_leads_list reports such a project as pinned_seat. seat_only with session null releases the pin."),
    Change(85, "Part 6 S2 (#1711): the huddle tools are now task_manager_*. tasks_list (was list), changes, schedules_list, add, update, state_request (was item_state_request), ask, reply, move, "
               "role_set, lead_set, leads_list, leads_update, group_create, group_update, answered_set (was mark_answered), delete, fork, batch_run (was batch), artifact_add (was artifact), "
               "entries_list (was inbox_list), entry_import (was inbox_file), progress_set (was progress), wait_update, guide. The old huddle_* names still answer, listed, for about a week and are then "
               "removed: call the new ones. huddle_focus keeps its name. The state fields list only the current names (open, working, todo, waiting, review); the retired names are still read."),
    Change(86, "Part 6 S4 (#1711): the rules say send where they said tell. A send is what Carnivore sends your session when the owner changed the list (it was a tell); the pasted line and every tool are unchanged."),
    Change(87, "Part 6 S6 (#1711): tool descriptions say send where they said tell (fire_now, fire_at, the add box entry line); no tool, argument or pasted line changed."),
    Change(88, "Section 28 (docs/reviewboard.md, Inline questions): a review board draws each question inline under the part of the page it names, not in a separate pane. "
               "Set `anchor` on every prompt to the id of the `anchors` entry (tagged data-rb-anchor in the page) it is about; a prompt with no anchor is drawn at the end of the board."),
    Change(89, "Section 28: the inline questions of rev 88 are withdrawn. Prompts are answered in the board's review fold-down again; anchor stays optional and still lets the owner point at a part."),
    Change(90, "Section 28 (docs/reviewboard.md, Layers, #1832 S2): task_manager_board_create and task_manager_board_revision_add take an optional `layer`. A `questions` layer asks a list of questions (yesno, choice, multi, toggle, text, longtext, each with a note) without a page: leave out html, "
               "or pass html as context with data-rb-anchor parts and set `anchor` on an item to draw it under that part; placement float puts them in one panel. His answers come back as {layer, v, values, notes} keyed by your item ids, absent meaning unanswered. No prompts with a layer."),
    Change(91, "Section 28 (docs/reviewboard.md, Layers, #1832 S4): `layer.kind: rows` reviews a list of rows without a page: each row has a title, optional tag, labeled lines, footnote and group, and its own picks (`choices` on the layer or the row, `pick` one or several, `suggest` marks your take and is never picked). "
               "His answer comes back as {layer: rows, v, values: {row id: choice id, or a list of ids when pick is several}, notes: {row id: text}}; a row the owner did not pick has no key. No prompts with a layer."),
    Change(92, "Section 28 (docs/reviewboard.md, Width, #1832): task_manager_board_create and task_manager_board_revision_add take an optional `max_width` (integer px, 480 to 2400) for a canvas page: the board holds that revision's page to the width, centered, and the owner gets a bar key to switch to full width. Absent means full width. Layers have a fixed width and ignore it."),
    Change(93, "Sections 5, 7 and 27 (owner's guards): while the owner's newest message on an item is unanswered, an info you post (omitted kind, info, attention) is "
               "stored as an answer quoting it (notify dropped; the answer carries stored_as_answer_to and owner_guard; not_a_question does not change it). "
               "Review means ready to close: task_manager_update review (or done_by_claude, a batch update, a fork's parent_state or fork_state) is refused, naming each reason, "
               "while their message is unanswered, your question there is open, a forked task is not done (a fork with parent_state review counts its own new fork), "
               "or a queued handoff (~/.handoff/pending/<name>.sh) the item text, review fields or thread names has no ~/.handoff/log/<name>.result yet. "
               "Your question, a fork or a message naming a queued handoff on an item in review moves it back to open (review withdrawn). "
               "Carnivore's own questions, a review board round and a cross_project reply are outside the answer guard; task_manager_answered_set is the way past your open question when the owner answered in the terminal."),
    Change(94, "Sections 3, 22 and 27: tasks are born open. Set or file state todo only when the owner explicitly asks to park that task (the add box's leading backlog word is their explicit ask), never to park your own follow-ups. A project's own skill or CLAUDE.md may override this default; the server does not refuse todo."),
    Change(95, "Sections 3 and 22: filing an add box entry, set state todo whenever their own text clearly asks to park it, in any words (a leading backlog, back burner or later, or plain wording like park this, for later, not now), not only a leading keyword; never when the text does not ask."),
    Change(96, "Section 17: markers replace flag colors. Mark a task with `marker` (diamond, square, triangle, circle, hexagon, pentagon, star, cross; one per task, \"\" clears) on task_manager_update, task_manager_reply or a batch op; reads carry `marker`. "
               "flag_color still works for now (purple is star, pink is cross, teal is hexagon, lime is circle) and flag_reason is ignored; huddle_focus is deprecated."),
    Change(97, "Section 28: a review board can run live: task_manager_board_live_set overwrites one working draft with no card and no state move, task_manager_board_milestone_add (\"bookmark that\") freezes it as a named revision and asks for review, task_manager_board_live_stop ends it; inline_picks draws prompts under their anchors."),
    Change(98, "Section 29: a session on do not disturb is refused (error dnd_not_assigned) when it updates, replies on, posts a page or progress on, or forks a task not assigned to it; ask the owner with task_manager_ask first (their answer lets you proceed), or repeat the write with reason (15+ characters), which is posted on the task for the owner."),
    Change(99, "task_manager_delete (and its old name huddle_delete) is no longer an MCP tool; to remove a task ask with task_manager_state_request action delete (section 27). huddle_focus is deprecated and switched off by default; mark the task with the marker argument of task_manager_update."),
    Change(100, "Section 30: pass task_item (the Task Manager item id) on every crosstalk_send about a task; crosstalk_reply inherits the parent's. The item shows the crosstalk trail built from it."),
    Change(101, "Sections 3 and 22: the todo wording is the shorter one master carries (todo items are not worked unless the owner asks); the two rev 93 pointer lines are gone, section 27 still holds both rules. No rule changed."),
    Change(102, "Sections 25 and 29 (#1981): a task you add (task_manager_add, the batch add op, inbox filing) is tagged to your own session automatically, and the owner's tick of a task you worked is sent to you even when it was never tagged."),
    Change(103, "Section 8: a thread message with quiet true is the owner's Comment: not an instruction, never sent to you as a reply, "
        "and it changes no state and reads nothing; the owner marks messages read only by Mark read or a saved reply or answer."),
    Change(104, "Section 26: the owner's reply or answer on a waiting task keeps it waiting unless the wait names the owner; task_manager_state_request has an action undo_completion to ask the owner to "
        "withdraw a closure; a thread message of kind correction (with retracts) is the owner withdrawing a completion or cancellation or cancelling the task, so stop yourself, delivery is not proof you did; "
        "a result you post on a cancelled task lands unread and the task stays cancelled."),
    Change(105, "Section 7: task_manager_update takes review_checks, a list of short things the owner must check before closing; a new list replaces the old one, [] clears it, and only the owner ticks them."),
    Change(106, "Sections 7, 8 and 26: shorter wording so the default answer fits its cap; no rule changed.", agent_facing=False),
    Change(107, "Sections 5, 6, 9 and 19: an unread info keeps the task in the owner's needs you as a read until the owner marks it read or the status changes; "
        "a new or reopened task lands open, so file it then move it on; every status change adds a system line to the thread (category status), which is not a post to answer."),
    Change(108, "Section 7: a fork is a subtask the owner sees in the subtasks tab; task_manager_tasks_list item of the parent lists its forks (id, title, status, owner), "
        "and review_checks is the checklist the owner ticks in the task."),
    Change(109, "Sections 27 and 33: review on a parent is refused while a subtask is not in review or done, the owner's tick "
        "is refused while a subtask is not done or a blocker stands, and a held task's blocked answer names the forks holding it.")
)

TASK_MANAGER_GUIDE_HASH = "0c3ab3b6f97ca167ec09ca8f1cca464ab194c522eefd0cf4cd27166899ddc8f2"

GUIDE_PATH = Path(__file__).resolve().parents[2] / "core" / "skills" / "bundled" / "huddle" / "SKILL.md"


def guide_hash(tools: Mapping[str, Any], guide_path: Path = GUIDE_PATH) -> str:
    digest = hashlib.sha256()
    for name in sorted(tools):
        digest.update(f"{name}\0{tools[name].description}\0".encode("utf-8"))
    digest.update(guide_path.read_bytes())
    return digest.hexdigest()


def guide_text() -> str:
    return GUIDE_PATH.read_text(encoding="utf-8")


def guide_answer(since_rev: Any = None, topic: Any = None, detail: bool = False) -> Dict[str, Any]:
    given = [name for name, value in (("since_rev", since_rev), ("topic", topic), ("detail", detail or None)) if value not in (None, 0, False)]
    if len(given) > 1:
        raise ValueError(f"pass only one of since_rev, topic and detail (got {', '.join(given)})")
    if since_rev not in (None, 0):
        return _changes_answer(since_rev)
    text = guide_text()
    if topic is not None:
        try:
            section = guide_sections.find(guide_sections.parse(text)[1], topic)
        except guide_sections.GuideTopicError as exc:
            raise ValueError(str(exc)) from exc
        return {"topic": f"{section.number}. {section.title}", "guide": section.text}
    return {"guide": text if detail else guide_sections.core_text(text)}


def _changes_answer(since_rev: Any) -> Dict[str, Any]:
    if isinstance(since_rev, bool) or not isinstance(since_rev, int) or since_rev < 0:
        raise ValueError("since_rev must be a non-negative integer (the guide_rev you last read)")
    lines = _entries(since_rev)
    if not lines:
        return {"up_to_date": True, "since_rev": since_rev}
    return {"since_rev": since_rev, "changes": lines, "hint": "call task_manager_guide with no arguments for the core rules, or topic for one section"}


def _entries(above: int) -> List[Dict[str, Any]]:
    return [{"rev": line.rev, "summary": line.summary} for line in TASK_MANAGER_GUIDE_CHANGELOG if line.rev > above and line.agent_facing]
