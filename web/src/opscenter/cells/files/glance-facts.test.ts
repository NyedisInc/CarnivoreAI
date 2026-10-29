import { describe, expect, test } from 'vitest';
import type { SessionGitStatus } from '../../api/types';
import { glanceOf, glanceWords } from './glance-facts';

function git(state: SessionGitStatus['state'], files = 0, truncated = 0): SessionGitStatus {
  return { state, repo_name: 'api', branch: 'main', counts: { staged: 0, unstaged: files, untracked: 0, conflicted: 0 }, files: Array.from({ length: files }, (_, i) => ({ path: `f${i}`, orig_path: null, index: ' ', worktree: 'M', kind: 'modified', submodule: false })), truncated, read_at: 1 };
}

describe('files glance', () => {
  test('counts the listed files and the ones cut past the cap (mutation: drop `truncated`)', () => {
    expect(glanceOf(git('ok', 2, 3))).toEqual({ kind: 'changed', count: 5 });
  });

  test('a repo with nothing changed reads clean', () => {
    expect(glanceOf(git('ok'))).toEqual({ kind: 'clean' });
  });

  test('an unread or unknown git is never clean (mutation: default to clean)', () => {
    expect(glanceOf(null)).toEqual({ kind: 'unread' });
    expect(glanceOf(git('unknown'))).toEqual({ kind: 'unread' });
  });

  test('not a repo and a paired computer say so', () => {
    expect(glanceOf(git('not_a_repo')).kind).toBe('no_repo');
    expect(glanceOf(git('remote')).kind).toBe('remote');
  });

  test('the words are catalog keys, the count a placeholder', () => {
    expect(glanceWords({ kind: 'changed', count: 5 })).toEqual({ key: 'glance.changed', vars: { n: 5 } });
    expect(glanceWords({ kind: 'clean' })).toEqual({ key: 'glance.clean' });
  });
});
