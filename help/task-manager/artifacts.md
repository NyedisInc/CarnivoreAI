---
title: Artifacts
slug: huddle/artifacts
parent: huddle
order: 10
features: [huddle]
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/artifacts.py
  - src/cplugs/huddle/artifact_post.py
  - src/cplugs/huddle/artifact_ticket.py
  - src/cplugs/huddle/routes_artifacts.py

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# Artifacts

Some things are easier to see than to read: a mock-up, a before and after, a
chart, a comparison. An agent can post one self-contained web page on an
item's thread as an **artifact**. You open it in a large window inside the
app, or pop it out into its own browser window.

## Where to find it

On the item's thread: a small card with the page's title, a one-line
description and an **open** key. Posting one marks the item unread.

## How to use it

1. Press **open** on the card. The page opens in a large in-app window
   (**page: title**).
2. Press **pop out** to open the same page in its own browser window.
3. Press **close** to go back to the thread.
4. If the agent needs an answer about the page, its question sits right under
   the card. Answer it there; the page itself cannot send anything back.

## What a page can and cannot do

The page is treated as untrusted code and runs locked down:

- It can run its own scripts and styles and show embedded images and fonts.
- It cannot load anything from the network, call the app's API, read cookies,
  storage or your login, open pop-ups, submit forms or navigate the app.
- It is stored with the item for as long as the item exists.

Opening a page uses a short-lived signed link (valid for an hour); opening it
again makes a fresh one.

## Troubleshooting

- **could not open the page.** The signed link was refused or the file is
  missing; close and press **open** again.
- **The page looks broken.** Anything it tried to load from the web was blocked
  by design. The agent must embed everything in the one file.

## Related pages

- [The thread and replies](thread-and-replies.md)
- [Questions and answer forms](questions-and-forms.md)

## For AI: key facts

- Post with `task_manager_artifact_add {item, title, description?, html | file_path}`:
  exactly one of `html` or `file_path` (absolute, `.html` or `.htm`, a regular
  file, not a symlink). Title 1 to 120 characters, description one line up to
  300, page up to 2 MiB.
- One self-contained document: inline all CSS and JS, embed images and fonts as
  `data:` URIs. No network, no `fetch`, no external links, no storage.
- Use an artifact only for what text cannot show; follow it with `task_manager_ask` on
  the same item when you need an answer.
- Readers of the thread see `artifact {title, description}`, never the page.
- Routes: `POST /api/v1/cplugs/huddle/items/{id}/artifacts`, `POST
  .../items/{id}/artifacts/{file_id}/ticket`, and the public, ticket-checked
  `GET .../artifact-view/{ticket}` served with a sandboxing Content Security
  Policy.
