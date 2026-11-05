/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import type { SessionGitStatus } from '../../opscenter/api/types';
import type { CheckpointList } from '../checkpoints/api';

const file = (path: string, kind: SessionGitStatus['files'][number]['kind']) =>
  ({ path, orig_path: null, index: '.', worktree: 'M', kind, submodule: false });

const status: SessionGitStatus = {
  state: 'ok', repo_root: '/work/repo', repo_name: 'repo', branch: 'main', head_short: 'abc1234', truncated: 0, read_at: 1,
  ahead: 0, behind: 0, upstream: null, counts: { staged: 0, unstaged: 1, untracked: 0, conflicted: 0 },
  files: [file('README.md', 'modified')],
};
const list: CheckpointList = {
  session_uuid: 'u-1',
  checkpoints: [
    { id: 31, prompt_uuid: 'p2', kind: 'turn', created_at: 1_790_000_000, work_tree: '/work/repo', pinned: true, left_out: ['.env'] },
    { id: 30, prompt_uuid: 'p1', kind: 'turn', created_at: 1_789_999_000, work_tree: '/work/repo', pinned: false, left_out: [] },
  ],
};

const preview = { id: 31, work_tree: '/work/repo', change: ['a.txt'], create: [], delete: ['new.py'],
  kept: [{ path: '.env', reason: 'left_out' }], fingerprint: 'fp-1' };
const blocking: string[] = [];
const held: number[] = [];
const fetched: string[] = [];
vi.mock('../../opscenter/api/session-git.svelte', () => ({
  sessionGit: () => ({ status: 'ok', data: status }),
  releaseSessionGit: () => {},
}));
vi.mock('../../opscenter/api/session-checkpoints.svelte', () => ({
  sessionCheckpoints: (rowId: number) => { held.push(rowId); return { status: 'ok', data: list }; },
  releaseSessionCheckpoints: () => {},
}));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../opscenter/api/auth.svelte')>()),
  authFetch: (path: string, init?: RequestInit) => {
    fetched.push(init?.method ? `${init.method} ${path} ${String(init.body)}` : path);
    if (path.endsWith('/revert/preview')) return Promise.resolve({ ...preview, blocked_by: [...blocking] });
    if (path.endsWith('/revert')) return Promise.resolve({ id: 31, safety_id: 40, changed: ['a.txt'], created: [], deleted: [], kept: [] });
    if (path.endsWith('/changes')) return Promise.resolve({ id: 31, files: [file('scripts/gen.sh', 'untracked'), file('old.txt', 'deleted')] });
    return Promise.resolve({ state: 'ok', text: '', truncated: false, untracked: false, binary: false, sensitive: false, directory: false });
  },
}));

const { default: FileDrawerGit } = await import('./FileDrawerGit.svelte');
const { setDrawerGitTarget, drawerGit } = await import('./git-view.svelte');

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  setDrawerGitTarget(null);
  document.body.replaceChildren();
  held.length = 0;
  fetched.length = 0;
  localStorage.clear();
  drawerGit.tab = 'files';
});

function open(rowId: number | null) {
  const target = document.createElement('div');
  document.body.append(target);
  const onOpenDiff = vi.fn();
  drawerGit.tab = 'changed';
  mounted.push(mount(FileDrawerGit, { target, props: { onOpenDiff } }));
  setDrawerGitTarget({ sessionId: 'ses_1', workdir: '/work/repo', rowId });
  flushSync();
  return { target, onOpenDiff };
}

const paths = (target: HTMLElement) => [...target.querySelectorAll('[data-git-path]')].map((p) => p.textContent);

test('a picked turn lists its own files and opens its own diff; now is the live status again', async () => {
  const { target, onOpenDiff } = open(7);
  expect(held).toEqual([7]);
  const pick = target.querySelector('[data-git-turn-pick]') as HTMLSelectElement;
  expect([...pick.options].map((o) => o.value)).toEqual(['now', '31', '30']);
  expect(pick.options[1]!.textContent).toContain('bookmarked');
  expect(paths(target)).toEqual(['README.md']);

  pick.value = '31';
  pick.dispatchEvent(new Event('change'));
  flushSync();
  await tick();
  flushSync();
  expect(fetched).toContain('/sessions/7/checkpoints/31/changes');
  expect(paths(target)).toEqual(['scripts/gen.sh', 'old.txt']);
  expect(target.querySelector('[data-git-left-out]')!.textContent).toContain('1');

  (target.querySelector('[data-git-diff="scripts/gen.sh"]') as HTMLButtonElement).click();
  const body = document.createElement('div');
  const cleanup = onOpenDiff.mock.calls[0]![1](body);
  flushSync();
  expect(fetched).toContain('/sessions/7/checkpoints/31/diff?path=scripts%2Fgen.sh');
  cleanup();

  pick.value = 'now';
  pick.dispatchEvent(new Event('change'));
  flushSync();
  expect(paths(target)).toEqual(['README.md']);
});

test('a session with no row id (a paired computer) reads no snapshots and draws no picker', () => {
  const { target } = open(null);
  expect(held).toEqual([]);
  expect(target.querySelector('[data-git-turn-pick]')).toBeNull();
  expect(paths(target)).toEqual(['README.md']);
});

test('revert opens the preview, is refused while blocked, and confirms with the preview fingerprint', async () => {
  const settle = async () => { for (let i = 0; i < 4; i += 1) { flushSync(); await tick(); } };
  const { target } = open(7);
  const pick = target.querySelector('[data-git-turn-pick]') as HTMLSelectElement;
  expect(target.querySelector('[data-git-revert]')).toBeNull();
  pick.value = '31';
  pick.dispatchEvent(new Event('change'));
  await settle();
  blocking.push('session carnivore_x is live in /work/repo');
  (target.querySelector('[data-git-revert]') as HTMLButtonElement).click();
  await settle();
  expect(fetched).toContain('/sessions/7/checkpoints/31/revert/preview');
  expect(document.querySelector('[data-revert-blocked]')!.textContent).toContain('carnivore_x');
  expect((document.querySelector('[data-revert-go]') as HTMLButtonElement).disabled).toBe(true);
  expect(document.querySelector('[data-revert-group="delete"]')!.textContent).toContain('new.py');
  (document.querySelector('[data-modal-close]') as HTMLButtonElement).click();
  await settle();

  blocking.length = 0;
  (target.querySelector('[data-git-revert]') as HTMLButtonElement).click();
  await settle();
  const go = document.querySelector('[data-revert-go]') as HTMLButtonElement;
  expect(go.disabled).toBe(false);
  go.click();
  await settle();
  expect(fetched).toContain('POST /sessions/7/checkpoints/31/revert {"confirm":true,"fingerprint":"fp-1"}');
  expect(document.querySelector('[data-revert-go]')).toBeNull();
  expect(pick.value).toBe('now');
});
