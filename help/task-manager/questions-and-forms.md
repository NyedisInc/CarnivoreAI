---
title: Questions and answer forms
slug: huddle/questions-and-forms
parent: huddle
order: 4
features: [huddle]
sources:
  - docs/task-manager.md
  - docs/task-manager-rich-questions.md
  - src/cplugs/huddle/structured.py
  - src/cplugs/huddle/rich_ask.py
  - src/cplugs/huddle/answers.py
  - src/cplugs/huddle/steer.py
  - web/src/cplugs/huddle/ask/TaskManagerAskForm.svelte
  - web/src/cplugs/huddle/ask/AskQuestion.svelte

**Stale page:** the huddle is being renamed and rebuilt as the Task Manager, so this page will be rewritten. Treat what it says as out of date until then.

# Questions and answer forms

When an agent is blocked on you, it asks on the item instead of stopping in a
terminal you may not be watching. A question moves the item to **needs you**,
counts in the tab badge and raises a toast, so it is the one kind of post that
reliably reaches you. This page explains the three shapes a question takes and
how to answer each.

## The three shapes

1. **A plain question.** One question as text. Any reply you write answers it.
3. **A typed form.** Each question has a type and comes with the agent's
   recommendation where it has one. The row shows one line, **N questions**,
   with an **answer** key that opens the form. Only the form's submit answers
   it; a plain reply on it is kept as a comment.

## Question types in a form

| Type | You answer with |
|---|---|
| yes or no | two buttons (the agent may relabel them) |
| pick one | one option; **other** adds a free-text box when the agent allows it |
| pick many | several options, sometimes with a minimum and maximum |
| rank | drag the options into order |
| short text | a one-line answer |
| long text | a paragraph |

## How to answer a form

1. Press **answer** on the row (or open the item: a form is drawn inline in the
   thread while it is open).
2. For each question, pick an answer, or press **take recommendation** to use the
   agent's marked pick. **take all recommendations** fills every question that
   has one.
4. Optionally write in **anything else** at the bottom, for anything the
   questions did not cover. It is never required.
5. Press **submit** (or Cmd/Ctrl+Enter). The counter on the key says how many
   required questions are left.

Submit saves the answer and queues the send like any other change: it goes
out with your other changes after a few quiet seconds, or at once when you press
**send to carnivore**. Holding Shift changes nothing.

### One-tap answers

When a post asks exactly one pick-one or yes-or-no question, it is answered
right in the thread: the options draw as pills and one tap submits. A question
that carries a command (for example a script for you to run) shows the command
with a copy key inside the question, and its options as pills, so a handoff
never leaves the sidebar.

### Dismissing a question

Shift-click the **answer** key, an inline pill or the prompt, or the form's
title strip to dismiss the question. Every question is recorded as skipped, the
answer reads "dismissed", and the item leaves needs you.

### Answered somewhere else

If you answered the agent in a terminal or chat, the agent should call
"mark answered" on the item so it stops waiting on you, and post an info
recording what you decided.

## What happens after you answer

- Your answer is stored as one message keyed by question, plus a text version.
  It is born read, so it never lights your own row.
- The row's question block disappears: answering clears the row. The thread
  keeps the form, its answers and anything else you wrote.
- The item leaves needs you and goes back to the section its status says.

## Examples

- An agent asks a pick-one question with the command
  `~/.handoff/handoff my-script` and the pills "ran it", "failed", "skip". You
  copy the command, run it, and tap "ran it".

## Troubleshooting

- **I replied but the form still waits.** A typed form is answered only by
  **submit**; your reply was kept as a comment.
- **The question shows nowhere on the row.** It always shows first, ahead of any
  newer info. If the item is in a folded section, the folded header carries a
  question mark with a count.

## Related pages

- [The thread and replies](thread-and-replies.md)
- [Reviews and ticks](reviews-and-ticks.md)
- Design of the typed forms: `docs/task-manager-rich-questions.md`

## For AI: key facts

- Ask with `task_manager_ask` only when blocked. Put background in `context` and the
  asks in `questions` (1 to 20 entries, 500 characters each). `text` is for a
  single plain question.
- A plain `task_manager_ask` text with two or more `?` and no `questions` is refused.
- Typed entries are objects `{id, type, prompt, required?, help?}` with `type`
  one of `yes_no`, `single`, `multi`, `rank`, `short_text`, `long_text`.
  `yes_no` `recommend.value` is a boolean, never the string "yes" or "no".
  Only `single` takes `command` (a string or `{text, lang?}`).
