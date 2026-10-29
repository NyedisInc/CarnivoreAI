---
title: Schedules and nudges
slug: huddle/schedules-and-nudges
parent: huddle
order: 7
features: [huddle, automations]
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/triggers.py
  - src/cplugs/huddle/recurrence.py
  - src/cplugs/huddle/schedule.py
  - src/cplugs/huddle/fire.py
  - src/cplugs/huddle/nudges.py
  - src/cplugs/huddle/nudge_sweep.py
  - src/cplugs/huddle/nudge_pick.py
  - src/cplugs/huddle/cplug.json

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# Schedules and nudges

The huddle can start work on its own. A **schedule** sends a project's session
a message about an item at a set time, once or on a repeat. A **nudge** wakes an idle
agent about work that has gone quiet. Both run in the app's backend, so they
work with every browser closed and survive a restart.

## Schedules

### What happens when an item comes due

At its time, Carnivore sends the item's project session a message about it, exactly as
**send to carnivore** would, with a line naming the item. If the project has no
running session, its newest asleep session is woken and sent to; if it has none at
all, a new session is started in the project folder with its default launch
profile, and sent to once it reaches its prompt. A busy session gets the send as
soon as it is free.

### How to schedule an item

1. Open the item and choose **schedule...** in its menu, or press the **+** on
   the **scheduled** section's header for a new scheduled item.
2. In the editor, set the **title**, the **instructions** (what the session is
   is sent when it fires), the **first time** and the **repeat**.
3. Save. The row shows a clock and the time ("today 3:00 pm", "tue 9:00 am") and
   the item sits in the **scheduled** section until it fires.

### Repeats

| Repeat | Fires |
|---|---|
| does not repeat | once |
| every day | daily at the picked time |
| on weekdays | on the days you toggle, at the picked time |
| every n hours | every 1 to 168 hours |
| monthly | on a day of the month at the picked time (the 31st falls back to the month's last day) |

Times of day are New York time and stay put across daylight saving changes. A
repeat that was missed while the app was down fires once at startup, then
carries on; a week offline is never a burst of fires.

### Changing, pausing and stopping

- Click a scheduled item's time to open the editor and change it.
- **pause** and **resume** a repeat on the row; a resume whose time has passed
  waits for the next occurrence instead of firing at once.
- **stop** ends it.
- **run now** in the editor fires the item immediately through the same path.
- Ticking or deleting the item cancels its schedule. An item in todo does not
  fire: a one-time trigger is spent and says why, a repeat waits quietly.

All scheduled items across every list are also listed, read only, on the
Automations page's huddle tab.

## Nudges

### What a nudge does

With the nudge on, Carnivore watches for work that has gone quiet and sends one
short send to the project's idle agent. It nudges about:

- **a claimed item gone quiet**: the agent is working it but nothing moved.
  The nudge says why the agent holds it: it set the item working itself, or it
  picked up your send and has not replied yet;
- **an item waiting to install**: built but not installed, with the agent idle;
- **an open item nobody claimed**, offered to an idle agent;
- **an idle agent holding nothing**, pointed at the top open item in your order.

It never nudges a busy session, never starts a new session (it may wake the
newest asleep one when the project has none running), and never nudges about an
item that waits on you, is scheduled, or is in todo. Each nudge leaves a quiet
line on the item's thread.

### When an item gets stuck

Each nudge waits longer than the last (one interval, then two, then three).
After the set number of nudges and one more interval with no change, the item
is flagged **stuck: unstick it**, moves to needs you, and one toast tells you.

### How to turn it on

- **For a project**: the bell on the project's bar in the huddle, or the swarm
  section of the edit project modal.
- **For one session**: the session's row menu in the sidebar, **swarm: nudge when
  idle** (it reads **swarm: stop nudging** while on). A session's own choice
  beats its project's.

## Settings

| Setting | Default | Range | What it does |
|---|---|---|---|
| nudge minutes | 60 | 15 to 1440 | quiet time before the first nudge |
| nudge tries | 3 | 1 to 10 | nudges before the item is flagged stuck |
| held send minutes | 30 | 1 to 1440 | how long a fire's send waits for a busy session |

## Troubleshooting

- **The row says "not sent: ...".** The fire failed; the reason is on the row and
  in the open item. A failed one-time fire is not retried: set a new time.
- **A scheduled item on the shared list never fired.** The shared list has no
  project to wake or start a session in; it needs a running agent session.
- **Nothing gets nudged.** The nudge is off for the project and the session, or
  every agent is busy.

## Related pages

- [Send to carnivore and the send queue](send.md)
- The Automations page: `docs/automations.md`

## For AI: key facts

- `fire_at` on `task_manager_add`, `task_manager_update` and batch add and update ops: ISO
  8601 with a UTC offset, in the future; `""` cancels. A time with no offset is
  refused.
- `repeat`: `{freq: "daily", time: "HH:MM"}`, `{freq: "weekly", byweekday:
  [0-6], time}` (Monday is 0), `{freq: "hourly", interval: N}`, `{freq:
  "monthly", monthday: 1-31, time}`; `""` stops repeating. `paused` pauses or
  resumes. `fire_now: true` runs it now (refused on approved or todo).
- Read `task_manager_schedules_list` before scheduling to see what already fires.
- An item's `start_trigger` shows `kind`, `fire_at`, `fired_at`, `last_error`,
  `repeat`, `paused`, `last_fired_at`.
- Nudge sends start `huddle nudge:`; answer on the item. Stuck items carry
  `needs_action: "unstick"` and `nudge: {count, last_at, stalled}`.
- Routes: `PATCH /api/v1/cplugs/huddle/items/{id}` (`fire_at`, `repeat`,
  `paused`), `POST .../items/{id}/run-now`, `GET/PUT .../lists/{key}/prefs`
  (`{nudge}`), `GET/PUT .../sessions/{session_uuid}/prefs`.
