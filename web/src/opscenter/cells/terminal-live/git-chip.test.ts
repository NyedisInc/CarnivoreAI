import { expect, test } from 'vitest';
import { chipParts, chipTitle, CHIP_DOT_MIN, CHIP_REPO_MIN, CHIP_SYNC_MIN } from './git-chip';
import type { SessionGitStatus } from '../../api/types';

const OK: SessionGitStatus = {
  state: 'ok', repo_name: 'cloudecode', branch: 'feature-x', detached: false, head_short: 'abc1234', unborn: false,
  upstream: 'origin/feature-x', remote: 'origin', ahead: 2, behind: 1,
  counts: { staged: 1, unstaged: 0, untracked: 0, conflicted: 0 }, files: [], truncated: 0, read_at: 1,
};

function drawn(width: number, status: SessionGitStatus = OK): string[] {
  const p = chipParts(status, width)!;
  return [p.repo && 'repo', p.branch && 'branch', p.dirty && 'dot', p.sync && 'sync'].filter(Boolean) as string[];
}

test('the fold drops ahead/behind, then the repo name, then the dot, never the branch', () => {
  expect(drawn(0)).toEqual(['repo', 'branch', 'dot', 'sync']);
  expect(drawn(CHIP_SYNC_MIN)).toEqual(['repo', 'branch', 'dot', 'sync']);
  expect(drawn(CHIP_SYNC_MIN - 1)).toEqual(['repo', 'branch', 'dot']);
  expect(drawn(CHIP_REPO_MIN - 1)).toEqual(['branch', 'dot']);
  expect(drawn(CHIP_DOT_MIN - 1)).toEqual(['branch']);
  expect(drawn(1)).toEqual(['branch']);
});

test('a detached head shows the short sha as the branch', () => {
  const p = chipParts({ ...OK, branch: null, detached: true }, 0)!;
  expect(p.branch).toBe('abc1234');
  expect(p.detached).toBe(true);
});

test('unknown is a word, a missing answer draws nothing, a non-repo draws nothing, clean has no dot', () => {
  expect(chipParts({ ...OK, state: 'unknown' }, 0)?.kind).toBe('unknown');
  expect(chipParts(null, 0, true)?.kind).toBe('unknown');
  expect(chipParts(null, 0)).toBeNull();
  expect(chipParts({ ...OK, state: 'not_a_repo' }, 0)).toBeNull();
  expect(chipParts({ ...OK, counts: { staged: 0, unstaged: 0, untracked: 0, conflicted: 0 } }, 0)!.dirty).toBe(false);
});

test('the tooltip carries the remote even when the width folded everything else away', () => {
  const t = (key: string, p?: Record<string, unknown> | null) => `${key}${p ? JSON.stringify(p) : ''}`;
  expect(chipTitle(OK, t)).toContain('git.chip.remote{"name":"origin"}');
  expect(chipTitle({ ...OK, state: 'unknown' }, t)).toBe('git.chip.unknown_title');
});
