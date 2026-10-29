---
title: Send to carnivore and the send queue
slug: huddle/send
parent: huddle
order: 8
features: [huddle]
ui_name: send to carnivore
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/sending.py
  - src/cplugs/huddle/send_queue.py
  - src/cplugs/huddle/service.py
  - src/cplugs/huddle/held.py
  - src/cplugs/huddle/send_pick.py
  - web/src/cplugs/huddle/TaskManagerSend.svelte

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# Send to carnivore and the send queue

## What a send is

The session receives one line naming the list and a read cursor, for example
that the list for a project changed and should be read with the
`task_manager_changes` tool from cursor 12. The agent reads only what moved since
then and answers in the task list. The cursor is where that session last read, so
one send covers every change since, and nothing is lost when several changes
ride one send.

## The queue

- **Queued**: a tick, a reply and an add are plain changes. Each one waits; once
  the list has been quiet for 10 seconds, or 45 seconds after the first change at
  the latest, one send goes out per list.
- **Sent at once**: your answer to an agent's question, an add box entry, and a
  press of the key. Before an immediate send into a session, any other list
  queued for that same session is sent first.
- **The key**: while changes are queued its background fills left to right
  toward the moment the send goes out, and restarts when a new change arrives.
  The badge counts the queued changes. Click it to send now.

The queue lives in memory. A restart drops it, but the changes stay unsent, so
the next press still sends them.

## Who gets the send

Each list is sent into its own session:

1. the session picked for that list, while it is still live: a pick made in the
   no-session pop-up (remembered in that window), or a stored pick set through
   the API;
2. otherwise the session that last used the task tools on that list;
3. otherwise the project's only agent session.

A session that has stopped is never picked. In all projects, one press sends
every list with changes, each into its own session.

### When a list has no session

If a project has no agent session of its own, nothing is sent until you choose.
A pop-up above the key lists the lists that need a pick, with up to four of
their waiting items, and offers for each:

- **start a new session** in the project's folder with its default launch
  profile, which is sent to once it reaches its prompt (up to 90 seconds);
- **a running session**, marked with the project it belongs to;
- **stop**, which sends nothing for this press.

## How it is delivered

- **Paste**: the line is typed into the session through the same guarded path
  every message uses. A session with a dialog or question open, or a pane that
  is a plain shell, is refused rather than typed into.
- **Channel event (prototype, off by default)**: with channel delivery on, new
  Claude sessions can receive the send as a Claude Code channel event instead of
  typed text, so the keyboard is never touched. Everything else still pastes.

## Settings

| Setting | Default | Range | What it does |
|---|---|---|---|
| send quiet seconds | 10 | 1 to 300 | quiet time before queued changes go out as one send |
| send cap seconds | 45 | 5 to 600 | the longest the first queued change waits (never below the quiet time) |
| held send minutes | 30 | 1 to 1440 | how long a send waits for a busy session |

A value you saved before the rename (tell quiet seconds, tell cap seconds, held
tell minutes) is still read as the matching send setting until you save a new one.

## Examples

- You tick five items in a row. Ten seconds after the last tick, the project's
  agent gets one send and reads all five.
- You answer an agent's question. The answer goes out at once, and the two
  ticks you made a moment earlier on another list for the same agent go first.

## Troubleshooting

## Related pages

- [The add box inbox](add-box-inbox.md)
- [Schedules and nudges](schedules-and-nudges.md)

## For AI: key facts

- A send line names `list <key>, since <cursor>`; read it with
  `task_manager_changes {list, since}` and answer in the task list, not the terminal.
- Routes: `POST /api/v1/cplugs/huddle/send {lists, targets?, queue?}` (answers
  per list `sent`, `queued`, `held`, `no_session`, `refused`), `POST
  .../lists/{key}/send {target?}` (409 `task_manager_pick_session` with no target and
  no default), `GET .../lists/{key}/sessions`, `PUT .../lists/{key}/send-target`,
  `GET .../send-queue`, `POST .../send-queue/flush`, `GET .../held`. The old
  paths ending `/tell`, `/tell-target`, `/tell-queue` and `/tell-queue/flush` still
  answer, and each use is counted until they are removed.
- Push topics: `cplug.huddle.sendq` (the queue; `cplug.huddle.tellq` is still
  named beside it for an old window), `cplug.huddle.held` (holds).
- Only a read by the list's own session, the session its last send went to, or
  the session a send is held for moves an item out of `waiting_to_send`.
- Settings keys: `sendQuietSeconds`, `sendCapSeconds`, `heldSendMinutes` (a value
  saved under `tellQuietSeconds`, `tellCapSeconds` or `heldTellMinutes` is read as
  the new key). Channel delivery: `PUT /api/v1/mcp-admin/channels {enabled}`.
