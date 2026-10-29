---
title: GitHub issue links
slug: huddle/github-issue-links
parent: huddle
order: 11
features: [huddle]
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/github_issue.py
  - web/src/cplugs/huddle/TaskManagerGithubIssue.svelte

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# GitHub issue links

An item can carry the GitHub issue it tracks, so the huddle item and the issue
point at each other in the huddle's own database. The open item shows a small
**#N** link that opens the issue in a new tab.

## Where to find it

Open the item. The link sits in its detail, under the "from" line when there is
one. Nothing shows when the item has no link.

## How to set it

There is no field for it on screen yet. It is set through the API or by an
agent:

- an agent passes `github_issue` on `task_manager_add` or `task_manager_update` (or the
  batch add and update ops);

Either side may set it on any item, and setting it never changes the item's
state. An empty value clears it.

## What counts as a valid link

- `https` only, host exactly `github.com` (no port, no credentials), path
  `/<owner>/<repo>/issues/<number>`.
- It is stored in one canonical spelling: a trailing slash, query or fragment
  is dropped.
- Anything else is refused (HTTP 400 on the route, a tool error on MCP).

## Examples

- An agent files an issue for "folder picker crash" and calls `task_manager_update`
  with that issue's URL. The item now shows **#1571**.

## Related pages

- [Items and states](items-and-states.md)

## For AI: key facts

- Field `github_issue` (stored in `items.github_issue`), returned on full items,
  lean summaries and compact MCP items only when set.
- Valid shape: `https://github.com/<owner>/<repo>/issues/<number>`; `""` clears;
  absent leaves it unchanged.
- A change bumps the item's revision and rides the normal list push.
