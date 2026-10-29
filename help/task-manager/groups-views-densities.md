---
title: Groups, views and densities
slug: huddle/groups-views-densities
parent: huddle
order: 6
features: [huddle]
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/groups.py
  - src/cplugs/huddle/item_marker.py
  - src/cplugs/huddle/focus.py
  - src/cplugs/huddle/progress.py
  - src/cplugs/huddle/steps.py
  - src/cplugs/huddle/cplug.json
  - web/src/cplugs/huddle/task-manager-prefs.svelte.ts
  - web/src/cplugs/huddle/task-manager-status-folds.svelte.ts

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# Groups, views and densities

A busy list needs shape. Groups file items by area (widgets, mcp tools, the
login page), the view decides how the list is sorted, and the density decides
how much each row shows. This page also covers the project accordion, colored
markers, and the live progress an agent can show on a row.

## Groups

A group is a named, foldable section of one list. Groups are areas, never
statuses: there is no "done" or "blocked" group, because the status sections
already say that.

1. **Make one**: press the folder key at the far left of the controls under the
   list (**new group**), type a name and press **create**. Names are unique in a
   list, ignoring case, up to 80 characters; a list holds up to 50 groups.
2. **File an item**: drag a row by its grip onto a group's header (or into the
   group), or use the item menu's **move to**, which lists each list's groups.
3. **Ungroup**: drag the row back above the groups, or pick the item's own list
   in **move to**.
4. **Rename, move or remove**: hover a group's header (always shown on a touch
   screen) for rename (or double-click the name), up, down and remove.
   **Removing a group never deletes an item**: its items become ungrouped.
5. **Fold**: the chevron on the header. A group's fold is saved on the server, so
   it folds on every device.
6. **Empty groups** are hidden unless **show empty groups** is on (the key beside
   new group). During a drag they appear as drop targets.

Agents are told to file every item in a group, to reuse the list's groups, and
to create one when nothing fits.

## Views

The view switch at the top of the list sorts the whole list. It is one setting
on every device.

- **by status** (the default): the status sections from top to bottom (needs
  you, question for you, ready to review, waiting to install, working,
  scheduled, open, todo, done). When the list has groups, each section splits
  into one subsection per group, labeled "section: group".
- **by group**: your groups, each split into the status subsections. Drag
  between groups here.

In both views a drag reorders a row inside its own section. Escape, or dropping
outside any target, cancels the drag and the row snaps back.

## Folds

- Status sections and subsections fold per device and per project (folding
  ready to review in one project does not fold it in another).
- In all projects, each project's block folds down to its title bar, which then
  shows a small chip per status with its count.
- A folded header shows what waits on you inside it: a mark and count for each
  open question, unread look and unread info.

## The project accordion

The **accordion** key, next to the density keys, keeps exactly one project open
in all projects. Clicking another project's bar opens it and closes the last
one; clicking the open project's bar scrolls it to the top instead of closing
it. The bars above the open project stack at the top and the bars below it at
the bottom. Your saved folds come back when you turn it off.

## Densities

Three keys beside the view switch; one setting on every device.

| Density | Each row shows |
|---|---|
| compact | one line: grip, check, status mark, title. A waiting question also shows its text on a second line. No reply box; opening the row answers it. |
| normal (default) | the title, the agent's latest post line, unread posts in full, the review block, and a reply box when the item is a question or a review |
| full | everything in normal plus the item's full description, without opening it |

## Markers

An agent can mark a task with one of eight solid shapes (diamond, square,
triangle, circle, hexagon, pentagon, star or cross), each in its own color, at
most one per task. The shape sits in the row's left margin. Beside the density
keys the list bar shows a key for each shape that is in use, and nothing when
none is: press a shape to see only those tasks, with every project and group
opened. A marker clears when you tick the task.

## Search and header filters

The magnifier key on the list bar opens a one-line search that matches loosely
("rvwbrd" finds "review board") on a task's title and text. While a search, a
marker or a status filter is on, everything opens and only matching tasks show;
the clear key drops the filter and your folds come back. On a project header the
info badge opens a list of that project's infos to read and dismiss, every other
status badge filters to that status and lights up (press it again to clear), and
a click on the project's name folds or unfolds it.

## When an agent points at rows

## Live progress on a row

- **Worker lines**: an agent working an item can show a line per worker under
  the title: a phase chip (queued, running, testing, installing, blocked, done),
  a short note and the elapsed time. A line with no update for 30 minutes dims
  as stale. The lines live in memory, so after an app restart the row shows
  nothing until the agent reports again.

## Project colors

In all projects each project title wears the project's color, picked from a
fixed palette in the project's edit screen. A color picked on one device shows
on every other.

## Troubleshooting

- **My group disappeared.** It is empty and **show empty groups** is off.
- **A drag will not land in another section.** Sections follow status; move the
  item by changing it, not by dragging.
- **A worker line says stale.** The agent has not reported for 30 minutes; it may
  be idle or blocked.

## Related pages

- [Items and states](items-and-states.md)
- [For agents: MCP tools and rules](for-agents.md)

## For AI: key facts

- Group tools: `task_manager_group_create {list, name}` (an existing name answers that
  group, `created: false`), `task_manager_group_update {group, name?, position?,
  remove?}`, and `group` (an id, or an area name created when new) on
  `task_manager_add` and `task_manager_move`. Agents never fold, and file only at the bottom
  of a group.
- Plugin settings: `view` (`status`, `area`, `claude`; `claude` is hidden and
  read as `area`), `density` (`compact`, `normal`, `full`), `accordion`,
  `showEmptyGroups`, `hideCompleted`.
- Markers: `marker` (`diamond`, `square`, `triangle`, `circle`, `hexagon`,
  `pentagon`, `star`, `cross`) on `task_manager_update`, `task_manager_reply`,
  `task_manager_add` and batch ops; `marker: ""` clears. The old `flag_color`
  still reads as a marker and `flag_reason` is ignored.
- `huddle_focus {list, items, open, clear?}` is deprecated (mark the task
  instead); it still highlights rows and marks them unread.
- `task_manager_progress_set {item, phase, note?, worker?}`: phases `queued`, `running`,
  `testing`, `installing`, `blocked`, `done`; note up to 300 characters, worker
  label up to 40, at most 8 workers per item.
