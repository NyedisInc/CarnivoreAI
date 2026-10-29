
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

UP, DOWN, ENTER, ESC, SPACE, LEFT, RIGHT = "\x1b[A", "\x1b[B", "\r", "\x1b", " ", "\x1b[D", "\x1b[C"
RULE = "─" * 100
HISTORY = ["❯ Call the AskUserQuestion tool exactly once.", "⏺ working"]


class AskPane:

    def __init__(self, questions: List[Dict[str, Any]], tab: int = 0, tabs_shown: Optional[int] = None) -> None:
        self.q = questions
        self.n = len(questions)
        self.tab, self.cursor = tab, 0
        self.tabs_shown = tabs_shown if tabs_shown is not None else self.n
        self.sel: Dict[int, Any] = {}
        self.typed: Dict[int, str] = {}
        self.notes: Dict[int, str] = {}
        self.notes_mode = False
        self.moved: set = set()
        self.keys: List[str] = []
        self.stray: List[str] = []
        self.closed = False
        self.rejected = False
        self.submitted: Optional[Dict[int, Any]] = None
        self.override: Optional[str] = None
        self.after_key: Optional[Callable[["AskPane"], None]] = None

    def multi(self, k: int) -> bool:
        return bool(self.q[k].get("multiSelect"))

    def preview(self, k: int) -> bool:
        return any(o.get("preview") for o in self.q[k]["options"])

    def layout(self, k: int) -> List[str]:
        rows = ["opt"] * len(self.q[k]["options"])
        if not self.preview(k):
            rows.append("other")
        if self.multi(k):
            rows.append("submit")
        return rows + ["chat"]

    def render(self) -> str:
        if self.override is not None:
            return self.override
        out = [*HISTORY, RULE]
        if self.closed or self.submitted is not None or self.rejected:
            return "\n".join([*HISTORY, "⏺ User answered Claude's questions:", "❯ ", RULE, "  📦 status line"])
        chips = "  ".join(f"{'☒' if k < self.n and self.done(k) else '☐'} Tab{k}" for k in range(self.tabs_shown))
        strip = f"←  {chips}  ✔ Submit  →"
        if self.tab == self.n:
            out += [strip, "Review your answers"]
            if any(not self.done(k) for k in range(self.n)):
                out.append("⚠ You have not answered all questions")
            for k in range(self.n):
                if self.done(k):
                    out += [f" ● {self.q[k]['question']}", f"   → {self.answer_text(k)}"]
            out += ["Ready to submit your answers?"]
            out += [("❯ " if self.cursor == 0 else "  ") + "1. Submit answers", ("❯ " if self.cursor == 1 else "  ") + "2. Cancel"]
            return "\n".join(out)
        k = self.tab
        if self.n > 1 or self.multi(k):
            out.append(strip)
        out.append(self.q[k]["question"])
        out += self.rows_text(k)
        out += [RULE]
        return "\n".join(out + self.chat_and_footer(k))

    def done(self, k: int) -> bool:
        s = self.sel.get(k)
        if s is None:
            return False
        return bool(s["ticks"] or s["other_on"]) if self.multi(k) else True

    def answer_text(self, k: int) -> str:
        s = self.sel[k]
        opts = self.q[k]["options"]
        if isinstance(s, tuple) and s[0] == "notes_only":
            return "(notes only)"
        if not self.multi(k):
            return s[1] if s[0] == "other" else opts[s[1]]["label"]
        return ", ".join([*(o["label"] for j, o in enumerate(opts) if j in s["ticks"]), *([self.typed[k]] if s["other_on"] else [])])

    def rows_text(self, k: int) -> List[str]:
        opts, multi, kinds = self.q[k]["options"], self.multi(k), self.layout(k)
        s = self.sel.get(k)
        out: List[str] = []
        glyph = lambda i: "❯ " if self.cursor == i else "  "  # noqa: E731
        preview = self.preview(k)
        for i, kind in enumerate(kinds):
            if kind == "opt":
                label = opts[i]["label"]
                if multi:
                    box = "✔" if s and i in s["ticks"] else " "
                    out.append(f"{glyph(i)}{i + 1}. [{box}] {label}")
                else:
                    mark = " ✔" if s and s[0] == "opt" and s[1] == i else ""
                    out.append(f"{glyph(i)}{i + 1}. {label}{mark}".ljust(34) + (self.box_line(k, i, 0) if preview else ""))
                if not preview:
                    out.append((" " * (9 if multi else 5)) + opts[i].get("description", "x"))
            elif kind == "other":
                text = self.typed.get(k)
                if multi:
                    on = bool(s and s["other_on"])
                    out.append(f"{glyph(i)}{i + 1}. [{'✔' if on else ' '}] {text if text else 'Type something'}")
                else:
                    mark = " ✔" if s and s[0] == "other" else ""
                    out.append(f"{glyph(i)}{i + 1}. {text + mark if text else 'Type something.'}")
            elif kind == "submit":
                out.append(f"{glyph(i)}   {'Next' if k < self.n - 1 else 'Submit'}")
        if preview:
            out += self.box_rows(k)
        return out

    def box_line(self, k: int, row: int, line: int) -> str:
        return "┌" + "─" * 30 + "┐" if row == 0 else ""

    def box_rows(self, k: int) -> List[str]:
        notes = self.notes.get(k)
        shown = ("Add notes on this design…" if self.notes_mode and not notes else notes) if (self.notes_mode or notes) else "press n to add notes"
        return [" " * 34 + "│ preview text" + " " * 17 + "│", " " * 34 + "└" + "─" * 30 + "┘", " " * 34 + f"Notes: {shown}"]

    def chat_and_footer(self, k: int) -> List[str]:
        kinds = self.layout(k)
        chat = len(kinds) - 1
        row = f"{'❯ ' if self.cursor == chat else '  '}" + ("Chat about this" if self.preview(k) else f"{chat + 1}. Chat about this")
        foot = ("Enter to select · ↑/↓ to navigate · n to add notes · Tab to switch questions · Esc to cancel" if self.preview(k)
                else "Enter to select · Tab/Arrow keys to navigate · Esc to cancel" if self.n > 1 or self.multi(k)
                else "Enter to select · ↑/↓ to navigate · Esc to cancel")
        return [row, foot]

    async def capture(self) -> str:
        return self.render()

    async def send(self, key: str) -> None:
        self.keys.append(key)
        if self.override is None and not (self.closed or self.rejected or self.submitted is not None):
            self.press(key)
        if self.after_key is not None:
            self.after_key(self)

    def kind_at(self) -> str:
        return self.layout(self.tab)[self.cursor]

    def arrive(self, tab: int) -> None:
        self.tab, self.cursor, self.notes_mode = tab, 0, False

    def press(self, key: str) -> None:
        if key == ESC:
            self.rejected = True
            self.stray.append("esc")
            return
        if self.tab == self.n:
            self.press_review(key)
            return
        k, kind = self.tab, self.kind_at()
        multi = self.multi(k)
        if self.notes_mode:
            if key == ENTER:
                self.sel[k] = ("opt", self.cursor) if k in self.moved else ("notes_only", self.cursor)
                self.arrive(k + 1)
            elif len(key) >= 1 and not key.startswith("\x1b"):
                self.notes[k] = self.notes.get(k, "") + key
            return
        if key == LEFT:
            if kind == "other" and self.typed.get(k):
                self.stray.append("left-in-other")
            else:
                self.arrive(max(0, k - 1))
        elif key == RIGHT:
            self.arrive(k + 1)
        elif key in (UP, DOWN):
            self.cursor = max(0, min(len(self.layout(k)) - 1, self.cursor + (1 if key == DOWN else -1)))
            self.moved.add(k)
        elif key == ENTER:
            self.enter(k, kind, multi)
        elif key == SPACE and multi and kind == "opt":
            ticks = self.sel.setdefault(k, {"ticks": set(), "other_on": False})["ticks"]
            ticks.symmetric_difference_update({self.cursor})
        elif key == "n" and self.preview(k) and kind != "other":
            self.notes_mode = True
        elif kind == "other" and not key.startswith("\x1b"):
            self.typed[k] = self.typed.get(k, "") + key
            if multi:
                self.sel.setdefault(k, {"ticks": set(), "other_on": False})["other_on"] = True
        else:
            self.stray.append(repr(key))

    def enter(self, k: int, kind: str, multi: bool) -> None:
        last = k == self.n - 1
        if kind == "opt" and not multi:
            self.sel[k] = ("opt", self.cursor)
        elif kind == "other" and not multi:
            if not self.typed.get(k):
                self.rejected = True
                self.stray.append("enter-empty-other")
                return
            self.sel[k] = ("other", self.typed[k])
        elif kind == "other":
            s = self.sel.setdefault(k, {"ticks": set(), "other_on": False})
            s["other_on"] = not s["other_on"]
            return
        elif kind == "submit":
            pass
        else:
            self.stray.append(f"enter-on-{kind}")
            return
        if last and self.n == 1 and not multi:
            self.submitted = dict(self.sel)
        else:
            self.arrive(k + 1)

    def press_review(self, key: str) -> None:
        if key == LEFT:
            self.arrive(self.n - 1)
        elif key in (UP, DOWN):
            self.cursor = max(0, min(1, self.cursor + (1 if key == DOWN else -1)))
        elif key == ENTER:
            if self.cursor == 0:
                self.submitted = dict(self.sel)
            else:
                self.rejected = True
