---
title: The add box inbox
slug: huddle/add-box-inbox
parent: huddle
order: 9
features: [huddle]
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/inbox.py
  - src/cplugs/huddle/inbox_store.py
  - src/cplugs/huddle/inbox_delivery.py
  - src/cplugs/huddle/inbox_filing.py
  - src/cplugs/huddle/mcp_inbox.py
  - src/core/skills/bundled/huddle/SKILL.md

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# The add box inbox

The box at the bottom of the huddle (**add an item for claude**) does not just
make an item from what you type. It hands your words to the project's most
recently active agent session, which splits them into separate items, gives
each a title, files each into the right group, and follows any direction you
led with. Your original words are kept for good.

## Where to find it

The bottom of the huddle, in the sidebar and every pop-out. Its list select
says which list the entry goes to; it follows the project of the terminal tab
you are on.

## How to use it

1. Type what you want, in plain words. Several requests in one go are fine.
2. Optionally lead with a direction:
   - **backlog** (or **back burner**, **later**): file it in todo, not worked yet.
   - **now** (or **do x now**, **start**): file it and start it.
   - **ask** (or **question**): file it as a question.
3. Press **add** or Enter. To type several items line by line, press the lines
   key beside the box: each line becomes its own entry, Enter is a new line, and
   Cmd/Ctrl+Enter adds.
4. The entry shows at the top of the list as a pending **filing...** row until a
   session files it.
5. Each filed item carries a **from the add box** line with your original text.

## What happens behind it

- The entry is stored with your raw text and sent at once to the list's most
  recently active live agent session. With no live session, the newest asleep
  one is woken. A new session is never started for it.
- A busy or refusing session leaves the entry queued; it is retried every few
  seconds while it waits.
- **Nothing is lost**: if no session files it within the fallback time (two
  minutes by default), the server adds it as one plain item with your text,
  exactly as typed.

## Settings

| Setting | Default | Where | What it does |
|---|---|---|---|
| file through a session | on | edit project modal, per project | off: the add box makes the item directly, as it used to |
| inbox fallback seconds | 120 (15 to 3600) | swarm settings page | how long an entry waits before it is added as a plain item |

The shared list has no session, so the add box always makes its items directly.

## Examples

## Troubleshooting

- **An entry sat on filing... then appeared as one plain item.** No session
  filed it in time (none running, or all busy). The text is exactly what you
  typed; edit or split it by hand, or ask an agent to.
- **The items landed on the wrong list.** Check the add box's list select before
  adding; it follows your active terminal tab, not the list on screen.

## Related pages

- [Items and states](items-and-states.md)
- [Send to carnivore and the send queue](send.md)

## For AI: key facts

- An inbox send reads `huddle inbox: ... file entry N with task_manager_entry_import`
  and quotes the raw text (line breaks may be flattened to " / ").
- Split separate asks into separate items; keep one task with steps as one item.
  Drop the leading direction words from `text`. Do not copy the raw text into
  the item: it already shows as `from_inbox`.
- `task_manager_entries_list` shows open entries with their full text. A late call (the
  entry already fell back or was filed) is refused; do not retry.
- Entry statuses: `queued`, `filing`, `filed`, `fallback`. Routes: `POST
  /api/v1/cplugs/huddle/lists/{key}/inbox`, `GET .../inbox/{id}`, `POST
  .../inbox/{id}/file`, `GET/PUT .../lists/{key}/inbox-prefs
  {file_through_session}`.
