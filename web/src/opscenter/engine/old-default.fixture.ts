import type { Layout } from './types';

export const OLD_DEFAULT_LAYOUT: Layout = {
  "v": 6,
  "rows": [
    {
      "id": "r2",
      "kind": "px",
      "size": 69,
      "slots": [
        {
          "id": "stat-running",
          "fr": 0.16666666666666666
        },
        {
          "id": "stat-sessions",
          "fr": 0.16666666666666666
        },
        {
          "id": "stat-projects",
          "fr": 0.16666666666666666
        },
        {
          "id": "stat-ledger",
          "fr": 0.16666666666666666
        },
        {
          "id": "stat-alive",
          "fr": 0.16666666666666666
        },
        {
          "id": "stat-subagents",
          "fr": 0.16666666666666666
        }
      ]
    },
    {
      "id": "r3",
      "kind": "px",
      "size": 198,
      "slots": [
        {
          "id": "running-sessions",
          "fr": 0.5533
        },
        {
          "id": "closed-sessions",
          "fr": 0.4467
        }
      ]
    },
    {
      "id": "r4",
      "kind": "px",
      "size": 213,
      "slots": [
        {
          "id": "projects",
          "fr": 0.33623
        },
        {
          "id": "skills",
          "fr": 0.33406
        },
        {
          "id": "plugins",
          "fr": 0.32971
        }
      ]
    },
    {
      "id": "r5",
      "kind": "px",
      "size": 160,
      "slots": [
        {
          "id": "themes",
          "fr": 0.28
        },
        {
          "id": "ledger",
          "fr": 0.36
        },
        {
          "id": "activity-log",
          "fr": 0.36
        }
      ]
    }
  ],
  "hidden": [
    "notes",
    "files",
    "scheduled-tasks",
    "keep-awake",
    "machine-stats",
    "changes",
    "task-manager",
    "task-manager-all",
    "crosstalk",
    "tasks",
    "tasks-all",
    "bookmarks",
    "bookmarks-all",
    "pipeline",
    "automations",
    "automations-all",
    "shell",
    "timeline",
    "questions",
    "developer",
    "task-list",
    "session-contents",
    "warroom"
  ],
  "heroCollapsed": false,
  "collapsed": [
    "themes"
  ]
};
