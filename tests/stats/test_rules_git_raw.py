from __future__ import annotations

import hashlib
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import pytest

from src.core.stats import rules
from src.core.stats.config import add_observed_annotation
from src.core.stats.rules import RULE_NAMES, RuleObserver, _SHA, _git
from tests.stats.test_observations import ready

PROJECT = 'proj'
MAX_FORKS_PER_PASS = 2
GIT_ENV = {'GIT_AUTHOR_NAME': 't', 'GIT_AUTHOR_EMAIL': 't@x', 'GIT_COMMITTER_NAME': 't',
           'GIT_COMMITTER_EMAIL': 't@x', 'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1'}


@pytest.fixture(autouse=True)
def isolated_git_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for key, value in GIT_ENV.items():
        monkeypatch.setenv(key, value)


def run(root: Path, *args: str) -> None:
    subprocess.run(['git', '-C', str(root), *args], check=True, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL)


def commit(root: Path, text: str | None, message: str, name: str = 'CLAUDE.md') -> None:
    path = root / name
    if text is None:
        path.unlink()
    else:
        path.write_text(text)
    run(root, 'add', '-A')
    run(root, 'commit', '-q', '-m', message)


def linear_repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    run(root, 'init', '-q')
    commit(root, 'one\n', 'add')
    commit(root, 'two\n', 'edit')
    commit(root, 'other\n', 'unrelated', name='README.md')
    commit(root, None, 'delete')
    commit(root, 'three\n', 're-add')
    return root


def merge_repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    run(root, 'init', '-q', '-b', 'main')
    commit(root, 'base\n', 'base')
    run(root, 'checkout', '-q', '-b', 'side')
    commit(root, 'side\n', 'side edit')
    run(root, 'checkout', '-q', 'main')
    commit(root, 'main\n', 'main edit')
    subprocess.run(['git', '-C', str(root), 'merge', 'side'], stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, check=False)
    (root / 'CLAUDE.md').write_text('resolved\n')
    run(root, 'add', '-A')
    run(root, 'commit', '-q', '-m', 'merge')
    return root


class OldObserver(RuleObserver):

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


def stored(store: Any) -> dict[str, list[tuple[Any, ...]]]:
    with store.connect(readonly=True) as db:
        return {
            'annotations': sorted(tuple(r) for r in db.execute(
                'SELECT occurred_at,label,rule_hash,reference,basis FROM stats_annotations')),
            'markers': sorted(tuple(r) for r in db.execute('SELECT * FROM stats_git_markers')),
            'progress': [tuple(r) for r in db.execute('SELECT * FROM stats_git_progress')],
        }


def one_pass(observer_cls: type[RuleObserver], tmp_path: Path, root: Path, tag: str,
             monkeypatch: pytest.MonkeyPatch, passes: int = 1) -> tuple[dict[str, list[tuple[Any, ...]]], int]:
    store = ready(tmp_path / tag)
    calls: list[list[str]] = []
    real = rules._git
    monkeypatch.setattr(rules, '_git', lambda cwd, args: calls.append(args) or real(cwd, args))
    observer = observer_cls(store, [])
    for _ in range(passes):
        observer._git_history(root, PROJECT)
        observer._git_file_cursor = 0
    monkeypatch.setattr(rules, '_git', real)
    return stored(store), len(calls)


def test_linear_history_costs_at_most_two_forks(tmp_path, monkeypatch):
    root = linear_repo(tmp_path)
    rows, forks = one_pass(RuleObserver, tmp_path, root, 'new', monkeypatch)
    assert forks <= MAX_FORKS_PER_PASS
    assert len(rows['markers']) == 3
    assert rows['progress'][0][3:] == (4, 1)


@pytest.mark.parametrize('builder', [linear_repo, merge_repo])
def test_new_pass_stores_the_same_rows_as_the_old_pass(tmp_path, monkeypatch, builder):
    root = builder(tmp_path)
    old, _ = one_pass(OldObserver, tmp_path, root, 'old', monkeypatch)
    new, _ = one_pass(RuleObserver, tmp_path, root, 'new', monkeypatch)
    assert new == old and old['markers']


def test_merge_commit_without_raw_lines_falls_back_to_one_rev_parse(tmp_path, monkeypatch):
    root = merge_repo(tmp_path)
    _, forks = one_pass(RuleObserver, tmp_path, root, 'new', monkeypatch)
    assert forks <= MAX_FORKS_PER_PASS + 1


def long_repo(tmp_path: Path) -> Path:
    root = tmp_path / 'repo'
    root.mkdir()
    run(root, 'init', '-q')
    for index in range(25):
        commit(root, f'v{index}\n', f'edit {index}')
    return root


def test_second_page_at_a_nonzero_offset_matches_the_old_pass(tmp_path, monkeypatch):
    root = long_repo(tmp_path)
    old, _ = one_pass(OldObserver, tmp_path, root, 'old', monkeypatch, passes=2)
    new, _ = one_pass(RuleObserver, tmp_path, root, 'new', monkeypatch, passes=2)
    assert new == old and len(new['markers']) == 25 and new['progress'][0][3:] == (25, 1)


def test_subfolder_project_records_its_own_rule_file_in_two_forks(tmp_path, monkeypatch):
    repo = tmp_path / 'repo'
    (repo / 'sub').mkdir(parents=True)
    run(repo, 'init', '-q')
    commit(repo, 'top one\n', 'top')
    commit(repo, 'sub one\n', 'sub add', name='sub/CLAUDE.md')
    commit(repo, 'sub two\n', 'sub edit', name='sub/CLAUDE.md')
    rows, forks = one_pass(RuleObserver, tmp_path, repo / 'sub', 'new', monkeypatch)
    assert forks <= MAX_FORKS_PER_PASS
    expected = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD:sub/CLAUDE.md'], capture_output=True,
                              text=True, check=True).stdout.strip()
    head = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'], capture_output=True,
                          text=True, check=True).stdout.strip()
    [newest] = [a for a in rows['annotations'] if a[3] == f'git:{head}:CLAUDE.md']
    assert len(rows['markers']) == 2
    assert newest[2] == hashlib.sha256(f'git-blob:{expected}'.encode()).hexdigest()
