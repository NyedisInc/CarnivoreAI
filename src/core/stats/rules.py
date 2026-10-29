from __future__ import annotations

import hashlib
import os
import re
import stat
import subprocess
from src.core.dev_tools import git_guard
import time
from pathlib import Path
from typing import Any

from .config import add_observed_annotation
from .plugin.extract import project_key

RULE_NAMES = ('CLAUDE.md', 'CLAUDE.local.md', 'AGENTS.md', '.claude/CLAUDE.md')
MAX_RULE_BYTES = 1024 * 1024
_SHA = re.compile(r'^[0-9a-f]{40,64}$')


def initialize(store: Any) -> None:
    with store.connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS stats_rule_sources (
          source_key TEXT PRIMARY KEY, digest TEXT NOT NULL, observed_at INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS stats_git_progress (
          project TEXT NOT NULL, filename TEXT NOT NULL, head TEXT NOT NULL,
          offset INTEGER NOT NULL, complete INTEGER NOT NULL,
          PRIMARY KEY(project,filename)
        );
        CREATE TABLE IF NOT EXISTS stats_git_markers (
          project TEXT NOT NULL, commit_id TEXT NOT NULL, filename TEXT NOT NULL,
          PRIMARY KEY(project,commit_id,filename)
        );
        ''')


def _git(cwd: Path, args: list[str]) -> str:
    if not git_guard.git_available():
        return ''
    result = subprocess.run(['git', '--no-pager', '-C', str(cwd), *args],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            text=True, timeout=3, check=False,
                            env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    return result.stdout if result.returncode == 0 else ''


class RuleObserver:

    def __init__(self, store: Any, global_roots: list[Path] | None = None) -> None:
        self.store = store
        self.globals = global_roots if global_roots is not None else [
            Path.home() / '.claude' / 'CLAUDE.md', Path.home() / '.codex' / 'AGENTS.md']
        self.projects: list[Path] = []
        self._cursor = 0
        self._git_file_cursor = 0
        self.last_state = 'pending'

    def add_projects(self, directories: list[str]) -> None:
        known = set(self.projects)
        for directory in directories:
            path = Path(directory).expanduser().resolve()
            if path.is_dir() and path not in known:
                known.add(path)
                self.projects.append(path)

    def run_batch(self, *, now: int | None = None) -> None:
        now = int(time.time()) if now is None else now
        self.last_state = 'ok'
        for path in self.globals:
            self._observe(path, '', path.name, now)
        if not self.projects:
            return
        root = self.projects[self._cursor % len(self.projects)]
        self._cursor += 1
        project = project_key(str(root))
        for name in RULE_NAMES:
            self._observe(root / name, project, name, now)
        self._git_history(root, project)

    def _observe(self, path: Path, project: str, reference: str, now: int) -> None:
        try:
            with path.open('rb') as handle:
                st = os.fstat(handle.fileno())
                if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_RULE_BYTES:
                    self.last_state = 'partial'
                    return
                body = handle.read(MAX_RULE_BYTES + 1)
            if len(body) > MAX_RULE_BYTES:
                self.last_state = 'partial'
                return
        except FileNotFoundError:
            body = None
        except OSError:
            self.last_state = 'partial'
            return
        digest = hashlib.sha256(body if body is not None else b'RULE-FILE-ABSENT').hexdigest()
        key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT enabled FROM stats_settings WHERE singleton=1').fetchone()[0]:
                return
            old = db.execute('SELECT digest FROM stats_rule_sources WHERE source_key=?', (key,)).fetchone()
            if old is None and body is None:
                return
            if old is not None and old[0] == digest:
                return
            add_observed_annotation(self.store, kind='rule', occurred_at=now,
                                    label=f'{reference}: ' + ('removal observed' if body is None else 'change observed' if old else 'baseline observed'),
                                    scope={'project': project} if project else {}, rule_hash=digest,
                                    reference=reference, basis='observed', connection=db)
            db.execute('INSERT INTO stats_rule_sources VALUES (?,?,?) ON CONFLICT(source_key) '
                       'DO UPDATE SET digest=excluded.digest,observed_at=excluded.observed_at',
                       (key, digest, now))

    def _git_history(self, root: Path, project: str) -> None:
        name = RULE_NAMES[self._git_file_cursor % len(RULE_NAMES)]
        self._git_file_cursor += 1
        try:
            head = _git(root, ['rev-parse', '--verify', 'HEAD']).strip()
            if not _SHA.fullmatch(head):
                return
            with self.store.connect(readonly=True) as db:
                progress = db.execute('SELECT head,offset,complete FROM stats_git_progress WHERE project=? AND filename=?',
                                      (project, name)).fetchone()
            if progress and progress['head'] == head and progress['complete']:
                return
            offset = progress['offset'] if progress and progress['head'] == head else 0
            history = _git(root, ['log', '-20', f'--skip={offset}', '--format=%H %ct', '--', name])
            entries = history.splitlines()
            deadline = time.monotonic() + 3
            processed = 0
            for line in entries:
                if time.monotonic() > deadline:
                    break
                bits = line.split()
                if len(bits) != 2 or not _SHA.fullmatch(bits[0]) or not bits[1].isdigit():
                    processed += 1
                    continue
                commit, stamp = bits[0], int(bits[1])
                blob = _git(root, ['rev-parse', '--verify', f'{commit}:{name}']).strip()
                if not _SHA.fullmatch(blob):
                    processed += 1
                    continue
                digest = hashlib.sha256(f'git-blob:{blob}'.encode()).hexdigest()
                with self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    if not db.execute('SELECT enabled FROM stats_settings WHERE singleton=1').fetchone()[0]:
                        return
                    exists = db.execute('SELECT 1 FROM stats_git_markers WHERE project=? AND commit_id=? AND filename=?',
                                        (project, commit, name)).fetchone()
                    if not exists:
                        add_observed_annotation(self.store, kind='rule', occurred_at=stamp,
                                                label=f'{name}: committed change {commit[:8]}',
                                                scope={'project': project}, rule_hash=digest,
                                                reference=f'git:{commit}:{name}', basis='git_commit', connection=db)
                        db.execute('INSERT INTO stats_git_markers VALUES (?,?,?)', (project, commit, name))
                processed += 1
            complete = len(entries) < 20 and processed == len(entries)
            with self.store.connect() as db:
                db.execute('INSERT INTO stats_git_progress VALUES (?,?,?,?,?) ON CONFLICT(project,filename) '
                           'DO UPDATE SET head=excluded.head,offset=excluded.offset,complete=excluded.complete',
                           (project, name, head, offset + processed, int(complete)))
        except (OSError, subprocess.TimeoutExpired):
            self.last_state = 'partial'
