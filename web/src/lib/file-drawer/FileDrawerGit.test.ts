/** @vitest-environment jsdom */
import { afterEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import type { SessionGitStatus } from '../../opscenter/api/types';
import { applyGitTags, buildGitTags, gitTagFor, treePathOf } from './git-tags';

const acquired: string[] = [];
let data: SessionGitStatus;
vi.mock('../../opscenter/api/session-git.svelte', () => ({
  sessionGit: (id: string) => { acquired.push(id); return { status: 'ok', data }; },
  releaseSessionGit: () => {},
}));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => ({
  ...(await importOriginal<typeof import('../../opscenter/api/auth.svelte')>()),
  authFetch: () => Promise.resolve({ state: 'ok', text: '', truncated: false, untracked: false, binary: false, sensitive: false, directory: false }),
}));

const { default: FileDrawerGit } = await import('./FileDrawerGit.svelte');
const { default: FileDrawerGitLine } = await import('./FileDrawerGitLine.svelte');
const { setDrawerGitTarget, drawerGit } = await import('./git-view.svelte');

const file = (path: string, kind: SessionGitStatus['files'][number]['kind']) =>
  ({ path, orig_path: null, index: '.', worktree: 'M', kind, submodule: false });

function fixture(): SessionGitStatus {
  return {
    state: 'ok', repo_root: '/work/repo', repo_name: 'repo', branch: 'main', head_short: 'abc1234', truncated: 0, read_at: 1,
    ahead: 1, behind: 0, upstream: 'origin/main',
    counts: { staged: 0, unstaged: 2, untracked: 2, conflicted: 0 },
    files: [
      file('src/deep/mod.ts', 'modified'), file('gone.txt', 'deleted'), file('.env.example', 'untracked'),
      file('newdir/', 'untracked'), file('README.md', 'modified'),
    ],
  };
}

const mounted: ReturnType<typeof mount>[] = [];
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  setDrawerGitTarget(null);
  document.body.replaceChildren();
  acquired.length = 0;
  localStorage.clear();
  drawerGit.tab = 'files';
});

test('a repo path maps onto the tree path whichever folder holds the other, and not otherwise', () => {
  expect(treePathOf('a/b.ts', '/r', '/r')).toBe('a/b.ts');
  expect(treePathOf('web/a.ts', '/r', '/r/web/')).toBe('a.ts');
  expect(treePathOf('other/a.ts', '/r', '/r/web')).toBeNull();
  expect(treePathOf('a.ts', '/r/inner', '/r')).toBe('inner/a.ts');
  expect(treePathOf('a.ts', '/x', '/r')).toBeNull();
});

test('files get their letter and tone, folders roll up to the strongest child, untracked folders cover their rows', () => {
  const index = buildGitTags(
    [file('src/a.ts', 'untracked'), file('src/deep/b.ts', 'modified'), file('src/deep/c.ts', 'deleted'),
      file('new/', 'untracked'), file('x.ts', 'conflicted')],
    '/r', '/r',
  );
  expect(gitTagFor(index, 'src/a.ts', false)).toMatchObject({ letter: 'U', tone: 'green' });
  expect(gitTagFor(index, 'src/deep/b.ts', false)).toMatchObject({ letter: 'M', tone: 'yellow' });
  expect(gitTagFor(index, 'x.ts', false)).toMatchObject({ letter: '!', tone: 'coral' });
  expect(gitTagFor(index, 'src', true)).toMatchObject({ letter: '•', tone: 'coral', kind: 'folder' });
  expect(gitTagFor(index, 'src/deep', true)).toMatchObject({ tone: 'coral' });
  expect(gitTagFor(index, 'new', true)).toMatchObject({ letter: 'U', tone: 'green' });
  expect(gitTagFor(index, 'new/inside.ts', false)).toMatchObject({ letter: 'U' });
  expect(gitTagFor(index, 'clean.ts', false)).toBeNull();
  expect(gitTagFor(index, 'other', true)).toBeNull();
});

test('applying tags writes attributes on workdir rows only and clears them', () => {
  const tree = document.createElement('div');
  tree.innerHTML = '<button class="config-editor-toggle" data-root="workdir" data-path="src"></button>'
    + '<button class="config-editor-file" data-root="workdir" data-path="src/a.ts"></button>'
    + '<button class="config-editor-file" data-root="user" data-path="src/a.ts"></button>'
    + '<button class="config-editor-toggle config-editor-toggle--root" data-root="workdir" data-path=""></button>';
  const index = buildGitTags([file('src/a.ts', 'modified')], '/r', '/r');
  expect(applyGitTags(tree, index)).toBe(2);
  const rows = tree.querySelectorAll('button');
  expect(rows[0]!.dataset.gitLetter).toBe('•');
  expect(rows[1]!.dataset.gitLetter).toBe('M');
  expect(rows[1]!.dataset.gitTone).toBe('yellow');
  expect(rows[2]!.hasAttribute('data-git-letter')).toBe(false);
  expect(rows[3]!.hasAttribute('data-git-letter')).toBe(false);
  applyGitTags(tree, null);
  expect(rows[1]!.hasAttribute('data-git-letter')).toBe(false);
});

test('no session named: nothing drawn and nothing read', () => {
  data = fixture();
  const target = document.createElement('div');
  document.body.append(target);
  const tabs: string[] = [];
  mounted.push(mount(FileDrawerGit, { target, props: { tree: null, onTab: (tab) => tabs.push(tab) } }));
  flushSync();
  expect(target.querySelector('[data-file-git]')).toBeNull();
  expect(acquired).toEqual([]);
  expect(tabs.at(-1)).toBe('files');
});

test('the changed files tab lists the answer in order, a row opens its diff, open hands the file over', () => {
  data = fixture();
  const target = document.createElement('div');
  const tree = document.createElement('div');
  tree.innerHTML = '<button class="config-editor-toggle" data-root="workdir" data-path="src"></button>';
  document.body.append(target, tree);
  const onOpenDiff = vi.fn();
  const onOpenFile = vi.fn();
  const tabs: string[] = [];
  mounted.push(mount(FileDrawerGit, { target, props: { tree, onTab: (tab) => tabs.push(tab), onOpenDiff, onOpenFile } }));
  setDrawerGitTarget({ sessionId: 'ses_1', workdir: '/work/repo' });
  flushSync();
  expect(acquired).toEqual(['ses_1']);
  expect(tree.querySelector('button')!.dataset.gitTone).toBe('yellow');
  expect(target.querySelector('[data-tab="changed"]')!.textContent).toContain('5');

  (target.querySelector('[data-tab="changed"]') as HTMLButtonElement).click();
  flushSync();
  expect(tabs.at(-1)).toBe('changed');
  expect(localStorage.getItem('carnivore.fileDrawerTab')).toBe('changed');
  const rows = [...target.querySelectorAll('[data-git-row]')].map((r) => [r.querySelector('[data-git-path]')!.textContent, r.querySelector('[data-git-letter]')!.textContent]);
  expect(rows).toEqual([['src/deep/mod.ts', 'M'], ['gone.txt', 'D'], ['.env.example', 'U'], ['newdir/', 'U'], ['README.md', 'M']]);

  (target.querySelector('[data-git-diff="src/deep/mod.ts"]') as HTMLButtonElement).click();
  expect(onOpenDiff).toHaveBeenCalledWith('src/deep/mod.ts', expect.any(Function));
  const body = document.createElement('div');
  const cleanup = onOpenDiff.mock.calls[0]![1](body);
  flushSync();
  expect(body.querySelector('[data-git-diff-view]')).not.toBeNull();
  cleanup();

  expect(target.querySelector('[data-git-open="gone.txt"]')).toBeNull();
  (target.querySelector('[data-git-open="README.md"]') as HTMLButtonElement).click();
  expect(onOpenFile).toHaveBeenCalledWith('README.md', '/work/repo', null);
});

test('the status line shows the chip, the nonzero counts and the short sha', () => {
  data = fixture();
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(FileDrawerGitLine, { target, props: {} }));
  flushSync();
  expect(target.querySelector('[data-git-line]')).toBeNull();
  setDrawerGitTarget({ sessionId: 'ses_1', workdir: '/work/repo' });
  flushSync();
  const line = target.querySelector('[data-git-line]')!;
  expect(line.querySelector('[data-gc="branch"]')!.textContent).toBe('main');
  expect(line.querySelector('[data-field="modified"]')!.textContent).toBe('2modified');
  expect(line.querySelector('[data-field="untracked"]')!.textContent).toBe('2untracked');
  expect(line.querySelector('[data-field="staged"]')).toBeNull();
  expect(line.querySelector('[data-field="sha"]')!.textContent!.trim()).toBe('abc1234');
});

test('a folder spelled through a symlink still tags, from the resolved spelling the answer carries', () => {
  data = { ...fixture(), repo_root: '/private/work/repo', working_dir_real: '/private/work/repo' };
  const target = document.createElement('div');
  const tree = document.createElement('div');
  tree.innerHTML = '<button class="config-editor-file" data-root="workdir" data-path="README.md"></button>';
  document.body.append(target, tree);
  mounted.push(mount(FileDrawerGit, { target, props: { tree } }));
  setDrawerGitTarget({ sessionId: 'ses_1', workdir: '/work/repo' });
  flushSync();
  expect(tree.querySelector('button')!.dataset.gitLetter).toBe('M');
});
