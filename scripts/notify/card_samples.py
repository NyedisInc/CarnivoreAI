
from __future__ import annotations

from typing import Any, Dict

PLANS = [
    ["a", "plan a", "patch the widget engine in place, smallest diff, 1 file"],
    ["b", "plan b", "split the engine into two modules, 4 files, one new test"],
    ["c", "plan c", "rewrite on the shared store, 9 files, needs a migration"],
]

SAMPLES: Dict[str, Dict[str, Any]] = {
    "yesno": {
        "type": "session.question", "agent": "api-docs", "computer": "nostromo", "title": "api-docs asks",
        "sub": "question on nostromo", "body": "merge exp/argent-widget-engine into master?", "cap": True,
        "acts": [["yes", "yes"], ["no", "no"], ["reply", "type an answer"]],
        "card": {"ask": "merge exp/argent-widget-engine into master?"},
    },
    "choice": {
        "type": "session.question", "agent": "billing-5", "computer": "nostromo", "title": "billing-5 asks",
        "sub": "pick one on nostromo", "body": "which plan should I build: A, B or C?", "cap": True,
        "acts": [["opt.1", "plan a"], ["opt.2", "plan b"], ["opt.3", "plan c"], ["reply", "type an answer"]],
        "card": {"ask": "which plan should I build: A, B or C?", "opts": PLANS, "multi": False, "qcount": 1},
    },
    "permission": {
        "type": "session.permission", "agent": "cloudecode-2", "computer": "studio", "title": "cloudecode-2 wants to run",
        "sub": "permission on studio", "body": "npm run build in web/", "cap": True,
        "acts": [["opt.1", "allow"], ["opt.2", "deny"]],
        "card": {"cmd": ["cd web && npm run build"], "dir": "web/", "tool": "bash",
                 "opts": [["a", "allow", ""], ["d", "deny", ""]]},
    },
    "file": {
        "type": "agent.message", "agent": "mixdown-2", "computer": "nostromo", "title": "mixdown-2 sent a file",
        "sub": "file on nostromo", "body": "mix-v3-notes.pdf, 214 KB", "cap": True,
        "acts": [["open_file", "open file"], ["save_file", "save to files"]],
        "media": {"id": "m_0123456789ab", "mime": "application/pdf", "bytes": 219136},
        "card": {"name": "mix-v3-notes.pdf", "bytes": 219136, "mime": "application/pdf", "from": "mixdown-2", "pages": 3},
        "full": {"head": ["mix v3 notes"], "poster": True},
    },
    "link": {
        "type": "agent.message", "agent": "carnivore_ai-2", "computer": "nostromo", "title": "carnivore_ai-2 sent a link",
        "sub": "link on nostromo", "body": "preview is ready · carnivore.ai", "cap": True,
        "acts": [["open_link", "open link"], ["copy_link", "copy link"]],
        "card": {"host": "carnivore.ai", "url": "https://carnivore.ai/preview", "title": "carnivore.ai preview build",
                 "mixed_script": False},
    },
    "image": {
        "type": "agent.message", "agent": "home", "computer": "studio", "title": "home sent an image",
        "sub": "image on studio", "body": "dashboard screenshot, 1170 by 2532", "cap": True,
        "acts": [["open", "open"], ["save", "save"]],
        "media": {"id": "m_1123456789ab", "mime": "image/png", "bytes": 884736, "w": 1170, "h": 2532},
        "card": {"w": 1170, "h": 2532, "caption": "dashboard screenshot"},
    },
    "video": {
        "type": "agent.message", "agent": "api-docs", "computer": "nostromo", "title": "api-docs sent a video",
        "sub": "video on nostromo", "body": "repro of the resize bug, 0:24", "cap": True,
        "acts": [["play", "play"], ["open", "open"]],
        "media": {"id": "m_2123456789ab", "mime": "video/mp4", "bytes": 4194304, "w": 1170, "h": 2532, "dur": 24},
        "card": {"dur": 24, "w": 1170, "h": 2532, "caption": "repro of the resize bug"},
    },
    "finished": {
        "type": "session.finished", "agent": "billing-5", "computer": "nostromo", "title": "billing-5 finished",
        "sub": "done on nostromo", "body": "turn took 6 min, 3 files changed", "cap": True,
        "acts": [["open", "open"], ["reply", "reply"]],
        "card": {"mins": 6, "files": ["src/core/sessions/resize.py", "web/src/lib/terminal/size-vote.ts",
                                      "tests/test_terminal_resize.py"], "nfiles": 3,
                 "stats": [[18, 4], [9, 2], [31, 0]]},
    },
    "died": {
        "type": "session.died", "agent": "cloudecode-2", "computer": "studio", "title": "cloudecode-2 died",
        "sub": "session died on studio", "body": "the pane exited with code 1", "cap": True,
        "acts": [["reopen", "reopen"], ["open", "open"]],
        "card": {"tail": ["> npm run build", "vite v6 building for production", "transforming 412 modules",
                          "rendering chunks", "client/dist/app.js  1.92 MB", "build finished in 14.2 s"], "exit": 1},
    },
    "update": {
        "type": "agent.update_ready", "agent": "claude code", "computer": "nostromo", "title": "claude code update ready",
        "sub": "agent update on nostromo", "body": "2 sessions run an older version", "cap": True,
        "acts": [["restart_agents", "restart them"], ["later", "later"]],
        "card": {"from": "2.1.301", "to": "2.1.312", "sessions": ["billing-5", "api-docs"]},
    },
    "appupdate": {
        "type": "app.update_available", "agent": "carnivore", "computer": "nostromo", "title": "carnivore update available",
        "sub": "app update", "body": "version 1.16.8 is ready to install", "cap": True,
        "acts": [["install", "install"], ["later", "later"]],
        "card": {"from": "1.16.7", "to": "1.16.8", "notes": [
            "sign in alert fires only on a proven sign out", "your global ai setup syncs across the pack",
            "notifications you can answer in place"]},
    },
    "swarm": {
        "type": "swarm.question_climbed", "agent": "home", "computer": "studio", "title": "swarm question for you",
        "sub": "from home on studio", "body": "two agents disagree on the card order", "cap": True,
        "acts": [["pick.1", "pick home's"], ["pick.2", "pick api-docs'"], ["answer", "type an answer"]],
        "card": {"ask": "which order should the board cards run in?", "asker_path": "home/board",
                 "positions": [["home", "smallest card first, so the board clears fast"],
                               ["api-docs", "riskiest card first, so a failure shows early"]]},
    },
    "crosstalk": {
        "type": "agent.message", "agent": "api-docs", "computer": "nostromo", "title": "message from api-docs",
        "sub": "crosstalk to home", "body": "tests are green, ready for you", "cap": True,
        "acts": [["reply", "reply"]],
        "card": {"text": "tests are green, ready for you",
                 "thread": [["home", "did the resize fix land?"], ["api-docs", "yes, merged to a branch"],
                            ["api-docs", "tests are green, ready for you"]]},
    },
    "signin": {
        "type": "provider.needs_login", "agent": "nyedis", "computer": "nostromo", "title": "sign in to nyedis",
        "sub": "claude account needs you", "body": "the renewal was refused, sign in again", "cap": True,
        "acts": [["sign_in", "sign in"]],
        "card": {"account": "nyedis", "provider": "claude", "reason": "renewal refused", "sessions": ["home", "mixdown-2"]},
    },
    "notice": {
        "type": "alert.other", "agent": "carnivore", "computer": "nostromo", "title": "carnivore alert",
        "sub": "alert on nostromo", "body": "something changed, open it to read more", "cap": False,
        "acts": [["open", "open"]],
        "card": {"title": "carnivore alert", "body": "something changed, open it to read more"},
    },
}
