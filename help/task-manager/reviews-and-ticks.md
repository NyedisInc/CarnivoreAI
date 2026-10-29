---
title: Reviews and ticks
slug: huddle/reviews-and-ticks
parent: huddle
order: 5
features: [huddle]
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/rules.py
  - src/cplugs/huddle/review.py
  - src/cplugs/huddle/lifecycle.py
  - web/src/cplugs/huddle/huddle-status.ts
  - web/src/cplugs/huddle/task-submit.ts

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# Reviews and ticks

When an agent finishes an item it hands it to you for review. You check it and
tick it, tick it with a note, or reply to send it back. The tick is yours
alone: no agent can approve an item, and an agent can never move an item you
approved.

## Where to find it

- **ready to review**: the section that holds items an agent marked done. Their
  stripe is cyan (blue) and they stay there until you act.
- **waiting to install**: items that are built and committed but not yet in the
  app you review in. The agent moves them to ready to review after the install.
- **needs you**: the section at the top for items waiting on your answer or
  flagged stuck. A review never goes here; it stays in ready to review.

## The review block

A finished item can carry a small block on the row, visible without opening
it, shown only while the item is in ready to review:

| Part | What it says |
|---|---|
| action tag | what you owe: **check and tick**, **check and tick to push**, **answer**, **read only** or **no action needed** |
| description | what changed and what to check, in formatted text (lists, tables, code) |
| link | a clickable link, when one helps: a page in the app, or a web address |
| location | a short place to look, such as "Settings, Huddle tab" |

A link inside the app opens in place; any other link opens in a new tab.

## How to use it

1. **Tick it**: check the box at the left of the row. The item reads **good**
   and moves to **done**.
2. **Tick it with a note**: press the note key on the open item, write your note
   (**a note for claude**) and save, then tick. A ticked item with a note reads
   **good, read the note**, so the agent knows to read it.
3. **Send it back**: write a reply on the item. A reply on a review item reopens
   it: it leaves ready to review, and goes back to working once the agent reads
   your reply. The review block hides, and comes back when the agent hands it to
   you again.
4. **Untick**: uncheck a done item. It returns to the agent's done mark if it had
   one, otherwise to open.
5. **Hide done items**: **hide completed** at the foot (the eye in the sidebar)
   hides checked items in every list. Unchecking one brings it back.

A tick is a change like any other: it is queued and sent to the agent, so the
agent learns of it within a few seconds. Ticking also marks every agent post on
that item read, and clears any marker and schedule on it.

## What a tick authorizes

The huddle records the tick; what it permits is set by each project's own
rules. **check and tick to push** is an agent asking you to approve a push. An
agent never pushes on its own because an item exists.

## Examples

- An agent finishes "folder picker" with the action **check and tick**, a
  description listing two screens to check and a link to the settings page.
  You open the link, look, and tick.

## Troubleshooting

- **A ticked item showed in open for a moment.** A tick waits to be sent to the
  agent, and the screen draws an item with an untold change as open. It moves to
  done once the queued send goes out, a few seconds later.
- **The review block is missing.** It only shows while the item is in ready to
  review and at least one review field is set.
- **An agent's write was refused on an item I approved.** That is the rule: an
  approval is yours to undo.

## Related pages

- [Items and states](items-and-states.md)
- [Send to carnivore and the send queue](send.md)

## For AI: key facts

- Hand over with `task_manager_update {state: "review", review_action,
  review_description, review_link?, review_where?}` in one call. Use
  `waiting` first when the work is committed but not installed.
- `review_action`: `tick`, `push`, `answer`, `read`, `none`; unset reads as
  `tick`. `review_description` renders markdown, up to 4000 characters;
  `review_where` up to 500; `review_link` is an in-app path starting with one
  `/` or an http(s) URL, up to 2000.
- An owner reply on a `review` item sets it back to `open` in the same
  write; the review fields are kept, only hidden.
- A tick stamps `joe_seq`, so the item reads `waiting_to_send` until a send or
  the agent's read carries it.
