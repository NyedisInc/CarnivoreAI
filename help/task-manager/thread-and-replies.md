---
title: The thread and replies
slug: huddle/thread-and-replies
parent: huddle
order: 3
features: [huddle]
sources:
  - docs/task-manager.md
  - src/cplugs/huddle/kinds.py
  - src/cplugs/huddle/files.py
  - src/cplugs/huddle/service.py
  - web/src/cplugs/huddle/task-manager-posts.ts
  - web/src/cplugs/huddle/task-manager-markdown.ts

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# The thread and replies

Every item has a thread: a short chat between you and the agents about that
one piece of work. This page covers how to read it, how to reply, what each
kind of agent post means, how unread works, and how to attach files.

## Where to find it

- **The open item.** Open a row and the thread sits under the item's
  description in its own scroll box (240 px tall in the sidebar, taller in a
  pop-out). Agent messages are on the left, yours on the right, each with its
  author mark, time and a kind tag. It opens scrolled to the newest message.
- **The row itself.** In normal and full density the collapsed row already shows
  the agent posts you have not read, in full, under the title, so most posts can
  be read and answered without opening anything.

## How to use it

1. **Reply**: type in the reply box (**reply to claude**) and press **reply** or
   Enter. The key turns to the confirm color as soon as the box holds text and
   reads "sent" briefly after it posts.
2. **Read an info**: click the small icon at the start of the post, or
   Shift-click anywhere on the post. Each post is read on its own.
3. **Expand a long post**: posts longer than about 240 characters or three
   lines show folded to their first line with a chevron. Click anywhere on the
   post to open or close it.
4. **Attach files**: paste a picture or file into a reply box, or drop files on
   it. Each uploads at once and shows as a chip (the x removes it). **reply**
   posts them with your words, or on their own.
5. **Copy a command**: a fenced code block in any post draws as a command area
   with a copy key in its corner.

When the item has no open question, the row shows no reply box on an open or
working item; open the item to reply there. On a question or a review the row
carries its own reply box.

## What each post means

| Post | Who | Unread for you | What it does |
|---|---|---|---|
| reply | you | no | your words; answers any plain question open on the item |
| info | agent | no, unless sent with notify | an fyi while it works; never changes the status or ends working |
| info with notify | agent | yes | marks the item unread and badges the tab, asks nothing |
| answer | agent | no | the agent answering a question you asked; shows your question quoted on top |
| question | agent | yes | the agent is blocked on you; see [Questions and answer forms](questions-and-forms.md) |
| look | agent (old) | yes | retired: old ones still show in the cyan look color, new ones cannot be posted |
| artifact | agent | yes | a card that opens an HTML page; see [Artifacts](artifacts.md) |

Post colors come from one table: question bright yellow, info violet, answer
orange, look cyan, review bright green.

## Unread

An item is unread for you when an agent added it, changed its text or state,
asked a question, posted a notify info, or pointed at it, after you last saw
it. Your own writes never make it unread, and any write of yours on it counts
as seeing it.

- **On the row**: the left stripe widens to 4 px. An unread plain info shows as
  dashes in the stripe instead.
- **Seeing it**: opening the row, or pressing a key or button inside the open
  row, clears the mark on every device.
- **Replying reads the item**: your reply marks every unread agent question,
  info and look on that item read. The row then shows only agent posts newer
  than your last reply. The thread and the database keep everything.
- **The tab badge** counts the items that need you, not every unread item.

## Formatting

Every huddle text surface, whoever wrote it, draws one safe markdown subset:
bold, italic, inline code, fenced code, lists with one nested level, small
headings, http and https links (opened in a new tab), pipe tables (number
columns right-align), and a `kv` fence of `key: value` lines. HTML shows as
plain text; nothing in a post can run code in the app.

## Files

- Files are kept in the huddle's own folder beside `huddle.db`, for as long as
  the item exists. An upload that never made it into a reply is swept after a
  day.
- In the thread, images show as thumbnails that open full size; other files
  show as chips that save on click.
- Agents read your files from their absolute paths on the thread, so a
  screenshot you paste is something the agent can look at.

## Troubleshooting

- **A file chip shows an error.** The server refused it; the chip says why (too
  large, or an image that is not really an image).
- **An agent's question is buried under infos.** The row always shows the open
  question first, ahead of any newer info.
- **The agent did not react to my reply.** A plain reply is queued and goes out
  with the next send a few seconds later; see
  [Send to carnivore and the send queue](send.md).

## Related pages

- [Questions and answer forms](questions-and-forms.md)
- [Artifacts](artifacts.md)

## For AI: key facts

- Message kinds (`messages.kind`): `reply` (owner), `info`, `answer`,
  `question`, `attention` (old look, read only now).
- `task_manager_reply` with no kind is an `info`. `notify: true` (info only) sets
  `attention_seq`, so the item is unread and the tab badges.
- `task_manager_reply` of kind info or answer whose last line ends in `?` is refused:
  questions go in `task_manager_ask`. `not_a_question: true` overrides.
- Reading one post: `POST /api/v1/cplugs/huddle/items/{id}/seen` with
  `{"message": <id>}`; no body clears only the unread mark.
- Files: `POST /api/v1/cplugs/huddle/items/{id}/files` (multipart), then
  `POST .../items/{id}/messages {text?, files: [ids]}`. On MCP reads each
  message's `files` carry an absolute `path`.
