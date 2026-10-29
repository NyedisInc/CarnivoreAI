---
title: Items and states
slug: huddle/items-and-states
parent: huddle
order: 2
features: [huddle]
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/rules.py
  - src/cplugs/huddle/lifecycle.py
  - web/src/cplugs/huddle/task-manager-status-sections.ts
  - web/src/cplugs/huddle/huddle-status.ts

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# Items and states

Every piece of work in the huddle is an item on a list. This page explains the
lists, what an item carries, the status each item shows, and who is allowed to
change what.

## Lists

- **One list per project.** Each project you have in Carnivore gets its own list.
- **The shared list.** One list that belongs to no project, for work that spans
  projects.
- **All projects.** A read-only view over every list at once: the shared list
  first, then each project under its own heading, in its own priority order.
  Everything you can do in a single list works here too. An add goes to the
  list the add box names.

Pick the list at the top of the huddle. When the huddle opens, the list on
screen and the add box's list both follow the project of the terminal tab you
are on. Moving to a tab with no project changes nothing. After that, the list
on screen stays where you put it while the add box keeps following your tab.

## What an item carries

| Part | What it is | Who writes it |
|---|---|---|
| title | a short summary, up to 120 characters | you or an agent, on any item |
| text | the item itself, up to 2000 characters | you on any item; an agent only on its own |
| note | your note, up to 4000 characters | you only |
| position | its place in the priority order (top is highest) | you only |
| thread | the chat on the item | both |
| state | the stored state (below) | both, within the rules |

An agent is told to write a title for any item you wrote without one, so your
list reads at a glance. A list holds at most 500 live items.

## The statuses

The server works out each item's status from its stored state and its
history; no screen computes it on its own. The status decides the section the
item sits in (by status view), the small icon at the left of the row, and the
color of the stripe on the row's left edge.

| On screen | Means | Stripe |
|---|---|---|
| needs you | waits on you: an unanswered question, or an item flagged stuck | question yellow |
| question for you | an agent asked and you have not answered | bright yellow |
| ready to review | the agent says it is done | cyan |
| waiting to install | built and committed, not yet in the app you review in | violet |
| working | an agent claimed it and is on it | green |
| scheduled | an open item with a pending time trigger | yellow, with a clock |
| open | nothing pending | a plain rule |
| todo | wanted, not today (stored as `todo`); agents leave it alone unless you ask | muted |
| done | you ticked it | green |

Sections run in that order from the top. Todo and done start folded.

### Working is a claim that lasts

An item reads working once an agent claims it, either by saying so or by
reading a change of yours that a send carried to it. The claim survives the
agent going idle, a restart and a dead session. It ends only when the agent
asks a question, marks the item done, sets waiting to install, sets it back to
open, moves it to todo, or when you tick or delete it. An agent posting an info
does not end it, and neither does your reply. A nudge about a working item
says which way the claim was made: you set it working, or you picked up its
send and have not replied (reply, review or set it open to release it).

### Your changes and the agent's read

When you change an item (add it, reply, note, tick, move), it waits for the
agent to read it. The server still tracks this as `waiting_to_send`, but the
screen shows such an item as open. A send or the agent's own read carries the
change; see [Send to carnivore and the send queue](send.md).

## How to use it

1. **Add an item**: type in the box at the bottom and press **add** (or Enter).
   See [The add box inbox](add-box-inbox.md) for what happens next.
2. **Reorder**: drag a row by its dotted grip, or focus the grip and press the
   up and down arrow keys. A drag moves a row inside its own section only; the
   server, not a drag, decides an item's status.
3. **Open an item**: click its row, or press Enter or Space on it.
4. **Use the item menu** (the move key on an open item): **move to** another
   list or group, **schedule...**, **title...**, **fork...**, and **move to
   todo** (which becomes **take off todo**).
5. **Remove an item**: the remove key on the open item. A removed item is a
   soft delete, kept in the database.
6. **Clear done items**: **remove completed (n)** at the foot of the list, then
   **remove** to confirm. It removes the checked items of the list on screen.

### Forking an item

**fork...** makes a new item beside the original, copying its title and text,
and sets the new item's state, and if you like the original's, in one step. Use
it to split a piece off a larger todo and file it as done or todo at once. The
fork shows "from" and the parent's title, which opens the parent. Each side
gets a one-line note on its thread saying where it came from or went.

### Moving an item

Moving sends the same item, with its thread, note, state and unread mark, to
the bottom of another list. An item another project's agent wrote shows a
small "from" line naming that project.

## Examples

- You drag "login bug" to the top of open. It stays first among the open items
  in every view and on every device.
- An item has three parts. You fork the finished part off and set the fork to
  done in the same dialog; the original stays open.

## Troubleshooting

- **An item I changed shows open, not working.** The agent has not read your
  change yet. Press **send to carnivore**, or wait for the queued send to go out.
- **I cannot drag a row into another section.** That is by design: sections
  follow the status, which only the item's own changes move.

## Related pages

- [Reviews and ticks](reviews-and-ticks.md)
- [Groups, views and densities](groups-views-densities.md)

## For AI: key facts

- Stored states (`rules.STATES`): `open`, `todo`, `review`,
  `done`; plus `waiting`, and `working` is a
  claim (`items.claude_working`, `items.claude_working_by`), not a stored state.
- Derived `status` (`lifecycle.status`), highest first: `done`, `todo`, `question`, `scheduled`,
  `waiting_to_send`, `review`, `waiting`, `working`, `open`.
- `needs_you` is a flag beside `status`, true exactly when `needs_action` is set
  (`answer`, `unstick`, or an old look's `tick` / `push` / `answer`). A review is
  never `needs_you`.
- Section order (`SECTION_ORDER`): needs_you, question, review,
  waiting, working, scheduled, open, todo, done.
- Limits: 500 live items per list, text 2000, note and message 4000, title 120.
- A write naming an older `expected_revision` is refused with 409 `task_manager_stale`.
