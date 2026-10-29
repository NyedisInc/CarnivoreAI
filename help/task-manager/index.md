---
title: The huddle
slug: huddle
parent: null
order: 1
features: [huddle]
ui_name: swarm
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/cplug.json
  - src/core/skills/bundled/huddle/SKILL.md
  - client/js/i18n/catalog.en.js

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# The huddle

The huddle is a shared, two-way todo list between you and the AI agents
working in your projects. You add work, drag it into priority order, answer
questions and tick what is good. The agents add items, say when they start and
finish, ask you questions on an item, and hand finished work to you for
review. Each item has a short thread, so the conversation about a piece of
work stays with that work instead of scrolling away in a terminal.

The app shows the huddle as **swarm** (the tab, the plugin row and the menu
link). Everything underneath, the plugin id, the routes, the MCP tools and the
database file, is still called `huddle`, and so are these pages.

## Where to find it

- **The left sidebar's tab strip**: the swarm tab. It stays in the strip with no
  close key while the **show tab** setting is on.
- **The menu tab**: the swarm row opens the plugin's settings page.
- **The tab's title row**: the pop out key opens the huddle in its own window.
  Every press opens another window, and each window keeps its own list choice.
- **The swarm panel**: clicking an agent opens its chat drawer, whose tasks
  viewer tab is the huddle list of that one agent.

## Turning it on

The huddle is a plugin. A clean install starts with it on. An install that
existed before the plugin shipped keeps whatever it had, which is off when
nothing was stored.

1. Open the menu tab and choose the plugins page.
2. Find **swarm** (marked plugin) and press its switch.
3. The switch grants the permissions it asks for: read sessions and projects,
   message a session, toasts, and agent writes.

Turning it off keeps every item. While it is off there is no tab, no menu
link, no huddle MCP tools, and every huddle route answers `409 cplug_disabled`.

## How the pieces fit

| Page | What it covers |
|---|---|
| [Items and states](items-and-states.md) | lists, items, the statuses and the colored stripe, who may change what |
| [The thread and replies](thread-and-replies.md) | the chat on each item, post kinds, unread, files on a reply |
| [Questions and answer forms](questions-and-forms.md) | numbered questions, typed forms, inline pills, dismissing |
| [Reviews and ticks](reviews-and-ticks.md) | ready to review, the review block, ticking, notes, needs you |
| [Groups, views and densities](groups-views-densities.md) | groups, by status and by group, densities, the project accordion, flags |
| [Schedules and nudges](schedules-and-nudges.md) | scheduled and repeating items, run now, the idle nudge |
| [Send to carnivore and the send queue](send.md) | how a session learns the list changed |
| [The add box inbox](add-box-inbox.md) | how a typed line becomes filed, titled, grouped items |
| [Artifacts](artifacts.md) | an agent's HTML page on a thread |
| [GitHub issue links](github-issue-links.md) | linking an item to the issue it tracks |
| [For agents: MCP tools and rules](for-agents.md) | every `huddle_*` tool and the rules an agent follows |

## Settings

All of these live on the swarm settings page (menu tab, swarm) and are one
value for you on every device and window.

| Setting | Default | Range | What it does |
|---|---|---|---|
| show tab | on | | keeps the swarm tab in the strip; off removes it on every browser |
| show empty groups | off | | draws groups that hold no items |
| hide completed | off | | hides checked items in every list |
| view | by status | by status, by group | how the list is sorted |
| density | normal | compact, normal, full | how much each row shows |
| accordion | off | | only one project open at a time in all projects |
| held send minutes | 30 | 1 to 1440 | how long a send waits for a busy session before it gives up and alerts you |
| send quiet seconds | 10 | 1 to 300 | quiet time before queued changes go out as one send |
| send cap seconds | 45 | 5 to 600 | the longest the first queued change waits |
| nudge minutes | 60 | 15 to 1440 | silence before an idle agent is nudged |
| nudge tries | 3 | 1 to 10 | nudges before an item is flagged to you as stuck |
| inbox fallback seconds | 120 | 15 to 3600 | how long an add box entry waits for a session to file it |

Two switches are per project rather than global: the nudge (the bell on the
project bar, or the edit project modal) and whether the add box files through a
session (the edit project modal).

## Examples

- An agent finishes a change and marks it done. The row moves into **ready to
  review** with a short review block saying what to check. You check it, tick
  it, and the agent sees the tick on its next read.
- An agent is blocked. It asks two numbered questions on the item. The row
  moves to **needs you**, the tab badge counts it, and you answer from the row.

## Troubleshooting

- **No swarm tab.** The plugin is off (plugins page) or **show tab** is off
  (swarm settings page). A new agent post never brings back a tab you switched
  off.
- **The tools are missing in an agent session.** The plugin is off, so its MCP
  tools are absent from the tool list. Turn it on and the agent can call
  `task_manager_guide`.

## Related pages

- [For agents: MCP tools and rules](for-agents.md)
- The engineering record: `docs/task-manager.md`
- The plugin model huddle was the first example of: `docs/cplugs.md`

## For AI: key facts

- Visible name `swarm`; every identifier is `huddle` (plugin id `huddle`,
  routes under `/api/v1/cplugs/huddle/`, tools `huddle_*`, file `huddle.db` in
  `<state_dir>/cplugs/huddle/`).
- One list per project (keyed by the project's row id), one shared list (key
  `all`, shown as shared), and the read-only aggregate "all projects"
  (client key `aggregate`). A Swarm agent's own thread is list `agent:<id>`.
- Changes are pushed, never polled: every write names the topic
  `cplug.huddle.list:<list>` on `resources.changed`.
- Call `task_manager_guide` before the first huddle write in a session; re-read it
  with `since_rev` when an answer's `guide_rev` rises.
