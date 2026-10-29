
# huddle: the interactive todo

## 1. Reading
<!-- core -->
- Read it with `task_manager_changes` using those two values. Answer in the huddle, not in the terminal.

## 2. Titles
<!-- core -->
- Every item has a short descriptive `title` (max 120 characters).
- If an owner-written item has no title, write one as soon as you see it.

## 3. Groups (every item is in one)
<!-- core -->
- EVERY item belongs to a group (the `group` field). No item is ever left ungrouped, including the ones you create: pass `group` on `task_manager_add`, or `task_manager_move` it right after.
- When you read a list, move any ungrouped item into the group that fits.
- If no group fits, create one (`task_manager_group_create`).
- Never make a group named after a status (no "Done", "Blocked", "In progress").

## 4. Guide revision
<!-- core -->
- These rules are the `task_manager_guide` tool's text; this skill is a copy of the same file.
- `task_manager_guide` is only needed before a write other than `task_manager_progress_set` and `task_manager_reply`. With no arguments it answers the core sections plus a one-line index of the rest; `topic: <number or name>` returns one section, `detail: true` returns the whole guide.
- Every huddle answer carries `guide_rev`; when it is higher than the one you last read, call `task_manager_guide` with `since_rev` set to that number. It answers `up_to_date` when nothing changed for agents, else a short summary of what did.

## 5. Reply kinds
<!-- core -->
- Never put a question in an info.

## 6. Working
<!-- core -->
- Set `state` to working with `task_manager_update` when you START. It is durable: it stays working across idle, restarts and dead sessions.
- Reading never makes an item working, sent or not. Only your own `working` does, so claim an item before you start it. Your claims end when you `/clear` or start a new conversation.
- Because it is durable, set `open` or `review` yourself when you stop an item.
- A new task, and one the owner reopens (reply, untick), lands `open`: file it (section 3), then move it on. Every status change leaves a system line on the thread (`category: status`), not a post to answer.
- Any move of the item out of `open` (review, waiting, todo, done), by anyone, ends your claim, and so does a question. A task on the swarm lane cannot be claimed with `task_manager_update` `working`: work it through the swarm card tools.

## 7. Review
<!-- core -->
- When finished, set `state` to `review`.
- Fill these in the same update. They show in the review block without opening the row. A review stays in the review section in the blue review color, never in "needs you", and its row shows no action tag:
  - `review_summary`: ONE plain line (about 140 characters, no markdown) saying what is done, shown above the folded description; set it when the description runs past a line or two. Absent: the description's first sentence.
  - `review_description`: what changed and what to check, in markdown (lists, bold, code, tables).
  - `review_link`: a clickable link, only when one helps (an in-app path or an https URL).
  - `review_where`: a short LOCATION ("Settings, Huddle tab"), only when useful; NOT a click path (no menu trail, version numbers or "reload").

## 8. Answers given outside the huddle

## 9. Surfacing
- A question moves an item into the "needs you" section. So does an unread info, as a read, until the owner marks it read or the status changes. A review never does.
- In normal density, pass `open: null`. The row shows the reply box, so it does not need opening.

## 10. Approval

## 11. Batching and lean answers
- Two or more edits (adds, state changes, replies, moves) in one go: send ONE `task_manager_batch_run` call (`list_id`, `ops`, at most 50), not one tool call each. An `add` op takes the `task_manager_add` fields (no item_id) and its own optional `list` (default `list_id`), so one call files items across projects. It answers per op `{item_id, ok, state, revision}` and is not atomic: read the `ok` flags, the earlier ops stay applied.
- Single writes (`task_manager_add`, `task_manager_update`, `task_manager_reply`, `task_manager_ask`, `task_manager_move`, `task_manager_answered_set`) answer lean BY DEFAULT: `{item_id, ok, state, revision}` (plus `message_id`). Pass `lean: false` only when you need the full item and its thread back.
- `task_manager_tasks_list` is a LEAN read by default: one summary row per open item (`id`, `number`, `title` (or the first 120 characters of the text), `status`, `section`, `unread`, plus `group`, `needs_action`, `forked_from`, `review_action` when set), no threads, no approved items (the answer says `approved_hidden`). Opt in with `fields` (a list of `text`, `note`, `thread`, `review`, `state`, `kind`, `revision`, ..., or `full` for the whole item), `include_approved: true`, `item: <id>` (ONE item in full with its thread: use it before you edit or reply on an item whose text you need), `limit` (default 100) and `cursor` (the previous answer's `next_cursor`; it is a paging offset, not the change cursor). Reading the list still counts as reading the approved items it hides.
- `task_manager_schedules_list` lists every scheduled item across all lists (`list` omitted or `all` means every list; soonest next fire first; `list` and `paused` filter it): read it before you schedule or pause something, to see what already fires and where.
- `huddle_focus` (deprecated and switched off by default; use `marker`) with `list: "all"` accepts items from any project's list.

## 12. Names
<!-- core -->

## 13. Formatting and data

## 14. Tool reference (moved out of the tool descriptions, which stay under 400 characters)
- **Working is durable** (see section 6): a read never makes an item working, with or without a send; only your `task_manager_update state: working` does.
- **Groups are areas** (widgets, mcp tools), never states. Each list answers its named groups (`id`, `name`, `position`); an item's `group` is null when ungrouped.
- **Typed questions**: see section 32.
- **Scheduling** (`task_manager_add` / `task_manager_update`): `fire_at` (ISO 8601 WITH a UTC offset, in the future; empty cancels) sends the item's session its prompt when it comes due, waking or starting the project's session first; approving or deleting the item cancels it and a todo item does not fire. An open item with a pending `fire_at` has status `scheduled` until it fires; a failed fire shows its error and leaves it open. `repeat` ({freq: daily, time: 'HH:MM'}, {freq: weekly, byweekday: [0-6, Monday is 0], time}, {freq: hourly, interval: N}, {freq: monthly, monthday: 1-31, time}; times are 24-hour in the app's configured time zone and DST-safe; empty string stops) re-arms after each fire; a missed occurrence while the app was down fires once. `paused` pauses or resumes a repeat; `fire_now: true` runs the item now through the same delivery (refused for an approved or todo item). `start_trigger` on an item shows all of it.
- **Forking**: `task_manager_fork` makes a new item beside one (title and text copied unless given); `fork_state` sets the fork, `parent_state` the original, in one transaction (never an approved state); the fork records `forked_from`. A fork is a subtask: `task_manager_tasks_list item` of the parent lists them under `forks`. `parent_waits: true` makes the original wait on its forks (section 31).
- **Moving**: `task_manager_move` sends an item to the bottom of another list (project ids from `projects_list`; `all` is the shared list) and/or into a group (an id or area name; a new name makes it; null ungroups). Numbering recomputes in both lists.
- **Stale writes**: `expected_revision` on `task_manager_update` refuses the write if the item changed since you read it.
- **Plain text vs markdown**: an item's own `text` is plain; formatted detail goes in a `task_manager_reply` post. `task_manager_batch_run` ops take that op's own tool fields (`add`, `update`, `reply`, `ask`, `move`, `mark_answered`, `delete`, `fork`); `list_id` is the list every item must be in (`all`, a project id, or `mine`); at most 50 ops; `stop_on_error: true` skips the rest after the first failure.

## 15. Live worker state (`task_manager_progress_set`)
<!-- core -->
- `worker` is your label ("orchestrator", "web", "api"). Each label keeps ONE line, replaced by its next call; up to 8 labels per item. Omit it for a single worker (label `main`).
- In a batch, use the op `progress` with `item_id`, `phase`, `note`, `worker`.
- A line with no update for 30 minutes shows dim as stale, and a line older than 6 hours is dropped. The lines live in memory only: re-send your current phase after an app restart.
- Do not spam it: one call per real change of phase or milestone.

## 16. Extending the huddle rules (personal add-on skills)
- When you see `stale_extensions`: read the changes (`task_manager_guide` with `since_rev` set to the add-on's `written_for`), check the add-on for anything that now conflicts or is redundant, fix it, and only then raise its `guide_rev` to the current one. Never raise it without checking.
## 17. Markers (guide rev 96, replaces the flag colors of rev 4)
- Set it with `marker` on `task_manager_update`, `task_manager_reply` (the task is marked after the post) or a `task_manager_batch_run` update or reply op. `marker: ""` clears it. An unknown name is refused with an error that lists the shapes. A marker never stands in for a status.
- Deprecated, still accepted for now: `flag_color` reads as a marker (purple is star, pink is cross, teal is hexagon, lime is circle) and `flag_reason` is ignored. `huddle_focus` is deprecated and switched off by default: mark the task instead.

## 18. Cards (guide rev 6)
- A task item is a card, shown in four columns worked out from its state: Todo (open, nobody holds it), In Progress (open and held, or a plain session is working it), Review (you marked it done, or a Swarm agent finished it) and Done (approved). Nothing is copied: the column is a view over the item.
- **Swarm agents drive cards only with the `swarm_card_*` tools** (`swarm_card_start`, `swarm_card_handoff`, `swarm_card_finish`, `swarm_card_release`, and for a project agent `swarm_card_list`, `swarm_card_deal`, `swarm_card_create`, `swarm_card_reorder`). A Swarm agent keeps its handoff current, finishes with a result and short how-to-validate steps, and never marks a card done.
- **Plain sessions keep the huddle tools and their claim** (`task_manager_update state: working`), which never lapses and is never dealt or handed off. You are a Swarm agent only when the Swarm spawned you (your brief says so); every other session is a plain session and works exactly as sections 1 to 17 say, with no card needed.
- The full design: `docs/swarm-cards.md`.

- **A question never goes in an info.** `task_manager_reply` of kind info or answer is refused when the last non-empty line ends in `?`, or when two or more numbered lines end in `?` (an omitted kind is an info). The refusal reads: "questions go in task_manager_ask with `questions`; an info is never answered". Move the question to `task_manager_ask` with `questions`.
- **A plain `task_manager_ask` text with two or more `?` and no `questions` is refused**: pass the questions as `questions`, one entry each, so each is answered on its own.
- **Every write answer carries `reaches_owner` (bool) and `reaches_owner_reason` (short text)**, also in lean answers and in each `task_manager_batch_run` result. Read them: `false` on something you needed the owner to see means you posted the wrong kind.

## 20. Your own project's list (guide rev 14)
- **Write to your own project's list** (`list: mine`). Every huddle write is checked against the project of the session making it: a write that lands on another project's list (a `list` argument, or an item, group or move target that lives there) is refused with a plain warning naming both projects.
- **A refused batch op fails alone** (`ok: false` with the warning); the other ops run as usual.

## 21. Nudges (guide rev 20)

- **A claimed item gone quiet** (`huddle nudge: no progress for N min on "..."`): post `task_manager_progress_set` and keep going, set `review` or `waiting` when it is done, ask with `task_manager_ask` when you are blocked, or set `open` when you stopped.
- **An open item nobody claimed** (`huddle nudge: "..." has sat open and unclaimed for N min`): if you are free, claim it with `task_manager_update` state `working` and keep going; ask with `task_manager_ask` if blocked; leave it open if you cannot take it.
- **You are idle with no claimed item** (`huddle nudge: you have been idle for N min and hold no swarm item. Pick up the next open item, "..."`): claim that item the same way, or ask.

## 22. Filing inbox entries (guide rev 25)

- **Leading directions steer it.** The words at the start of the text (or of one request inside it) are instructions to you, not part of the item. Drop them from `text`:
  - `backlog x` (also `back burner x`, `later x`): state `todo`, because the leading word is their explicit ask to park it. You do not work it. The ask need not be a leading keyword: their own text saying "park this", "for later" or "not now" about a request also files that item `todo`. When their text does not ask to park it, the item is born `open`.
  - `now x` (also `do x now`, `start x`): state `working`. You file it and start it, as with `task_manager_update state: working`.
  - `ask x` (also `question x`): state `question`; the item's text is the question, or pass `ask: {context, questions}` for typed questions.
  - nothing leading: state `open`.
- **Title and group every item** as in sections 2 and 3: a short title, filed into the area group it belongs to (`group` is an id or an area name).
- A late call (the entry already fell back or was filed) is refused with how it ended; do not retry.

## 23. Artifacts: show a page (guide rev 26)

- **One self-contained HTML document, up to 2 MB.** Inline all CSS and JS; embed images and fonts as `data:` URIs. Nothing external loads: no network, no CDN, no fonts from the web, no `fetch`, no links out, no cookies or storage, and the page cannot talk back to the app.
- **Prefer text for text.** An artifact is for what a paragraph cannot show. Give a plain `title` and a one-line `description` saying what to look at.
- **A question goes beside it, not inside it.** To get an answer, follow the artifact with `task_manager_ask` on the same item; it sits right under the card. The page has no buttons that reach you.
- It marks the item unread (like an info with `notify`). Use `file_path` (absolute, `.html`, not a symlink) for a page you wrote to disk; pass exactly one of `html` or `file_path`.

## 24. Your items on every answer (guide rev 30)

Every huddle answer can carry `your_items` (up to 5 of `{id, title, state, age_min}`) and `your_items_more`: the items you hold in `working` (your claim) or `waiting` (on your project's list). It is what you still owe: finish it, install it, look at it on the live page, then set `review` with a review or `task_manager_ask` if blocked. The field is absent when you hold nothing.

## 25. The session that holds an item working owns its sends (guide rev 34)

- `reopen` takes an approved item back to `open` (or `waiting` via `to_state`); `close` ends an open one approved (their approve is their tick).
- `undo_completion` asks the owner to undo a closure. A `correction` message (`retracts`) means the owner undid one or cancelled the task: stop (delivery proves nothing). A late result on a cancelled task lands unread and it stays cancelled.
- Every request waits in their approvals inbox. The card shows the title, current and target state and your `reason` (500 characters at most); nothing changes until the owner approves. The answer is `pending` with an `act_...` id: read the outcome with `approval_wait`; it is also a thread line (applied, not applied because the item changed, or denied).
- Asking again about the same item while a request is pending updates that one card (new reason); it never adds a second. Ask once with a real reason; do not retry a denial.
- A reopen of an item that is not approved, or a close of one that is, is refused before any card is filed: change those yourself with `task_manager_update`.

## 27. Movement rules (guide rev 57 to 61, 64)

- **An info after their unanswered message is an answer (rev 93).** His newest message on an item is unanswered until you post an `answer` or a question after it, or set `review` after it; a form submit and a review board round need no answer; Carnivore's questions never answer the owner. While it is unanswered, an info you post (an omitted kind, `info`, or `attention`) is stored as an `answer` quoting it, `notify` dropped (an answer never marks the item unread), and the result carries `stored_as_answer_to` (their message id) and an `owner_guard` note, in lean and batch answers too. `not_a_question` does not change it. A reply with `file_paths` stays an info and the note says to answer in a separate reply. A `cross_project` reply is never changed. Send `kind: answer` with `quote` yourself.

## 28. Review boards: show a mockup in rounds (guide rev 63, 68, 69, 89, 90, 91, 96)

- **`task_manager_board_create {name, title, task, summary, html or file_path, viewport, prompts, anchors}`** starts a board for the huddle item `task` and posts revision r1. **`task_manager_board_revision_add {board, summary, html or file_path, answers_round, prompts}`** adds the next one. `task_manager_boards_list` and `task_manager_board_get {board, since_round}` read them. **`task_manager_board_focus {board, revision?}`** puts the board on their screen (a row in their browser list, shown in the center screen); use it to point the owner at a revision you just posted. Revisions never change; a typo fix is a new revision.
- **Or ask a list of questions with a `layer`, no page needed.** Pass `layer: {kind: "questions", v: 1, title, items: [...]}` instead of `prompts` and leave out `html`: the board draws the questions inside its frame. An item is `{id, kind, label}` with kind `yesno`, `choice` (pick one, `options`), `multi` (`options`, `max` is enforced, `min` only shows as unanswered), `toggle`, `text` or `longtext`, plus optional `help`, `group`, `required`, `default` and `anchor`. An `anchor` (declared in `anchors`) draws the question right under that part of your page if you also pass `html` with `data-rb-anchor` parts; `placement: "float"` puts every question in one panel at the frame's edge instead. Each question has a note key. His answer comes back (`revision.draft`, a round's `payload`) as `{layer, v, values: {item id: value}, notes: {item id: text}}`; an unanswered item has no key, so absent means unanswered, never zero. A layer revision carries no `prompts`. `layer: {kind: "canvas"}` is the same as `payload_mode: true`.
- **Or review a list of rows with a `rows` layer.** Pass `layer: {kind: "rows", v: 1, title, choices: [{id, label, tone}], rows: [...]}` with no `html`: the board draws each row with its own picks and a note, like a review page of findings. A row is `{id, title}` plus optional `tag` (a small chip), `lines` (up to 8 `{label, text}` plain-text lines such as you had / now / my take), `meta` (a footnote such as a sha), `group` (consecutive rows sharing it get one heading), `anchor`, `choices` (this row's own picks, replacing the layer's), `suggest` (a choice id marked as your take, never picked for the owner) and `default` (a pick you carry over from their last round; the board carries nothing itself). `choices` take a `tone` of `ok`, `push`, `later` or `none`, which only colors them. `pick: "several"` lets a row take a list of picks (default one). His answer comes back as `{layer: "rows", v: 1, values: {row id: choice id, or a list of ids when pick is several}, notes: {row id: text}}`; a row the owner did not pick has no key. At most 200 rows and 12 choices.
- **A revision posts a card on the task and, by default, puts the task in review** (`request_review: false` posts only the card). Another project's task needs `cross_project: true`, like every huddle write. Never hand-edit a board's files; the tools are the only writer.
- **`inline_picks: true` draws each prompt right under its `anchor` row** on the page, in the trusted tray layer; tag block-level parts (a heading, a paragraph, a table row, a list item) with `data-rb-anchor` and name them in `anchors`. Dragging or editing on the page is not supported.

## 29. Roles: the project lead, do not disturb and tagged agents (guide rev 65 to 67, lead changes rev 78, 79, 81 and 84, do-not-disturb claims rev 98)

## 30. Offer a schedule, and read the thread a send names (guide rev 72)

- **When the owner accepts, their reply on the thread says "schedule this".** Then call `task_manager_add` with `fire_at` set to the offered `when` and that title, and reply with the date you scheduled. Do not offer a time you would not file yourself, and offer at most one per reply.
- **Always pass `task_item` on a crosstalk send about a task (guide rev 100).** `crosstalk_send` takes an optional `task_item` (the Task Manager item id); a `crosstalk_reply` inherits its parent's when you give none. It is how the task is traced across sessions: the item shows a crosstalk trail (who, to whom, when, first line) built from it. Leave it out only when the message is not about a task.

## 31. Waiting: say what and when, the stale timer, checks and the callback (guide rev 73, forks rev 83)

## 32. Typed questions (task_manager_ask forms)
<!-- core -->

## 33. Subtasks, the review lock and blockers (guide rev 109)

- **A subtask is a fork** (`task_manager_fork`; `forked_from` names the parent). `task_manager_tasks_list` `item` of the parent lists them.
- **His tick.** Refused while a subtask is not `done` (one in `review` still locks it) or a blocker stands; their screen says why. Name the subtasks in `review_description`.
- **Blockers.** A task waiting on its forks (section 31) is held: your moves stay `waiting`, `blocked` names the forks, their tick is refused. It clears when they finish, or with `task_manager_wait_update {item, result: cleared, reason}`. A park never blocks review.
- **Review checks are not a lock**: the owner is warned, not stopped. Tasks already past these rules stay as they are; only the next move is checked.
