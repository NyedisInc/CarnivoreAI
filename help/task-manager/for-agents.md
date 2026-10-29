  - docs/task-manager.md
  - src/cplugs/huddle/mcp.py
  - src/cplugs/huddle/mcp_inbox.py
  - src/cplugs/huddle/mcp_artifact.py
  - src/cplugs/huddle/own_list.py
  - src/cplugs/huddle/steer.py
  - src/cplugs/huddle/your_items.py
  - src/cplugs/huddle/guide_rev.py

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# For agents: MCP tools and rules

Agents use the huddle through the carnivore MCP server's `huddle_*` tools. This
page lists every tool and the standing rules. The rules themselves have one
canonical copy, the bundled skill `src/core/skills/bundled/huddle/SKILL.md`,
which the `task_manager_guide` tool returns; this page is a map of it, and the guide
wins where they differ.

## Before the first write

1. Call `task_manager_guide` once per session before your first huddle write.
2. Every huddle answer carries `guide_rev`. When it is higher than the one you
   read, call `task_manager_guide {since_rev: <the old rev>}` for just the changes.

## The tools

### Reading

| Tool | Does |
|---|---|
| `task_manager_guide` | the rules, `guide_rev` and the changelog; `since_rev` for only what changed |
| `task_manager_tasks_list` | one list as lean summary rows (no threads, approved hidden); `item` for one item in full; `fields`, `include_approved`, `limit`, `cursor`; `aggregate: true` for every list |
| `task_manager_changes` | only what changed after `since`; omit `list` for every list; your own posts are left out unless `include_mine: true` |
| `task_manager_schedules_list` | every scheduled item across all lists, soonest first |
| `task_manager_entries_list` | add box entries still waiting to be filed |

### Writing

| Tool | Does |
|---|---|
| `task_manager_add` | add an item (with `title`, `group`, `kind`, `fire_at`, `repeat`, review fields, `marker`, `github_issue`) |
| `task_manager_update` | your own item's text; any item's title, review block, marker, schedule, issue link; state `open`, `working`, `waiting`, `todo`, `review` |
| `task_manager_reply` | a post on the thread: `info` (default), `info` with `notify: true`, or `answer` with `quote` / `quote_text` |
| `task_manager_ask` | a question when you are blocked: `context` plus `questions` (plain strings or typed objects) |
| `task_manager_move` | move an item to another list's bottom, and/or into a group |
| `task_manager_fork` | a copy beside an item, setting both sides' states in one transaction |
| `task_manager_group_create`, `task_manager_group_update` | make, rename, move or remove a group |
| `huddle_focus` | DEPRECATED and switched off by default, mark tasks with `marker` instead: highlight rows (and mark them unread) in every open huddle view |
| `task_manager_progress_set` | a live worker line on an item: phase, short note, worker label |
| `task_manager_artifact_add` | post one self-contained HTML page on a thread |
| `task_manager_entry_import` | file an add box entry as one or more items |
| `task_manager_batch_run` | up to 50 ops in one call (add, update, reply, ask, move, mark_answered, delete (refused for agents), fork, progress); not atomic, read each `ok` |

Single writes answer lean by default: `{item_id, ok, state, revision}`. Pass
`lean: false` only when you need the whole item back.

## The standing rules

1. **Answer in the huddle, not the terminal.** A send names a list and a
   cursor: read it with `task_manager_changes` and reply on the items.
2. **Title and group everything.** Write a title on any owner item that has
   none. Every item belongs to a group named for an area, never a status.
3. **Say when you start.** `task_manager_update state: working` when you begin. The
   claim is durable, so set `open` or `review` yourself when you stop.
5. **Hand over for review** with `review` and the review fields in one
   update, always with a `review_action`. Use `waiting` first when the
   work is committed but not yet installed.
6. **Ask only when blocked, and ask well**: `task_manager_ask` with `context` and
   short, numbered `questions`, or a typed form. Never put a question in an
   info: a reply whose last line ends in `?` is refused.
9. **Write to your own project's list** (`list: mine`). A write to another
   project's list is refused unless the call carries `cross_project: true`, and
   then the item records where it came from.
12. **Batch** two or more edits into one `task_manager_batch_run`.

## What you still owe

Every huddle answer can carry `your_items` (up to five of `{id, title, state,
age_min}`) and `your_items_more`: the items you hold as working, and the
waiting to install items on your project's list. Finish, install, check, then
hand over or ask. A nudge also says why you hold each working item (you set
it working, or you picked up its send and have not replied); reply, review or
set it open to release a pickup claim.

## Approvals

## Swarm cards

## Related pages

- [The huddle](index.md)
- [Questions and answer forms](questions-and-forms.md)
- [Reviews and ticks](reviews-and-ticks.md)
- The MCP server: `docs/mcp-server.md`

## For AI: key facts

- 19 tools: `task_manager_guide`, `task_manager_tasks_list`, `task_manager_changes`,
  `task_manager_schedules_list`, `task_manager_entries_list`, `task_manager_add`, `task_manager_update`,
  `task_manager_reply`, `task_manager_ask`, `task_manager_answered_set`, `task_manager_move`,
  `task_manager_fork`, `task_manager_group_create`, `task_manager_group_update`, `huddle_focus`,
  `task_manager_progress_set`, `task_manager_artifact_add`, `task_manager_entry_import`,
  `task_manager_batch_run`. There is no delete tool: ask with `task_manager_state_request` action `delete`.
- `list` takes `all` (shared), a project id, or `mine`.
- Guide revision at this page's `verified_at`: 33
  (`TASK_MANAGER_GUIDE_REV`, `src/cplugs/huddle/guide_rev.py`).
