/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const fake = vi.hoisted(() => ({
  tree: {} as Record<string, unknown[]>,
  listing: [] as unknown[],
  git: {} as Record<string, unknown>,
  openResult: 'opened' as 'opened' | 'unavailable' | 'refused',
  readLevel: [] as Array<[string, string | null, string]>,
  findIn: [] as Array<[string, string | null, string]>,
  opens: [] as Array<[string, string, string, string]>,
  paths: [] as string[],
}));

vi.mock('../../api/auth.svelte', () => ({
  auth: { state: 'unknown' },
  initAuth: () => {},
  ApiError: class extends Error {},
  authFetch: () => Promise.resolve({}),
}));

vi.mock('../../../lib/file-drawer/tree-api', () => ({
  readLevel: (root: string, folder: string | null, path: string) => {
    fake.readLevel.push([root, folder, path]);
    return Promise.resolve({ root, tree: fake.tree[`${root}:${path}`] ?? [] });
  },
  findIn: (root: string, folder: string | null, q: string) => {
    fake.findIn.push([root, folder, q]);
    const hits = (fake.tree[`${root}:`] ?? []).filter((node) => (node as { name: string }).name.includes(q));
    return Promise.resolve({ root, tree: hits, truncated: false });
  },
  openInFilesList: (sessionId: string, root: string, path: string, kind: string) => {
    fake.opens.push([sessionId, root, path, kind]);
    return Promise.resolve(fake.openResult);
  },
  openPathInFilesList: (path: string) => { fake.paths.push(path); return Promise.resolve(); },
}));

vi.mock('../../api/sessions.svelte', () => ({
  sessions: { get data() { return fake.listing; } },
}));

vi.mock('../../api/session-git.svelte', () => ({
  sessionGit: (id: string) => ({ data: fake.git[id] ?? null, refresh: () => Promise.resolve() }),
  releaseSessionGit: () => {},
}));

import Cell, { FILES_WIDGET } from './Cell.svelte';
import FramedFiles from './fixtures/FramedFiles.svelte';
import { META } from '../../engine/meta';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { stateKey } from '../../widgets/shell/widget-state.svelte';

function node(relPath: string, isDir: boolean): unknown {
  return { name: relPath.split('/').pop(), rel_path: relPath, is_dir: isDir, read_only: false, is_ignored: false, children: [] };
}

function gitWith(files: unknown[], root = '/work/api'): unknown {
  return {
    state: 'ok', repo_root: root, working_dir_real: root, repo_name: root.split('/').pop(), branch: 'main', detached: false,
    head_short: 'a1b2c3d', unborn: false, ahead: 0, behind: 0, counts: { staged: 0, unstaged: files.length, untracked: 0, conflicted: 0 },
    files, truncated: 0, read_at: 1,
  };
}

function listed(id: string, folder: string): unknown {
  return { session_row_id: 1, tmux_session: `carnivore_${id}`, session: { id, working_dir: folder } };
}

async function settle(ms = 0): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, ms));
  flushSync();
}

let apps: ReturnType<typeof mount>[] = [];

function draw(props: Record<string, unknown> = {}, framed = false): HTMLElement {
  const target = document.createElement('div');
  document.body.appendChild(target);
  const base = { width: 320, height: 400, meta: META.files, instance: 'files', page: 'home', scope: { sessionId: 'ses_1', rowId: 1, workingDir: '/work/api', projectId: null } };
  apps.push(mount(framed ? FramedFiles : Cell, { target, props: { ...base, ...props } as never }));
  flushSync();
  return target;
}

const rowOf = (target: HTMLElement, key: string): HTMLElement | null => target.querySelector(`[data-key="${key}"]`);

beforeEach(() => {
  localStorage.clear();
  fake.tree = {
    'workdir:': [node('src', true), node('README.md', false)],
    'workdir:src': [node('src/index.ts', false)],
    'user:': [node('CLAUDE.md', false)],
  };
  fake.listing = [listed('ses_1', '/work/api'), listed('ses_2', '/work/web')];
  fake.git = { ses_1: gitWith([{ path: 'src/index.ts', orig_path: null, index: '.', worktree: 'M', kind: 'modified', submodule: false }]) };
  fake.openResult = 'opened';
  fake.readLevel = [];
  fake.findIn = [];
  fake.opens = [];
});

afterEach(() => {
  for (const app of apps) unmount(app, { outro: false });
  apps = [];
  document.body.innerHTML = '';
  vi.unstubAllGlobals();
});

describe('a file click', () => {
  test('opens it as a files list row for the session it shows, and says so', async () => {
    const target = draw();
    await settle();
    rowOf(target, 'node:workdir:README.md')!.click();
    await settle();
    expect(fake.opens).toEqual([['ses_1', 'workdir', 'README.md', 'file']]);
    expect(target.querySelector('[role="status"]')?.textContent?.trim()).toBe('opened README.md in the files list');
  });

  test('that cannot be opened says why out loud and never falls back to the old editor', async () => {
    const legacy = vi.fn();
    vi.stubGlobal('ConfigEditorModal', { open: legacy });
    fake.openResult = 'unavailable';
    const target = draw();
    await settle();
    rowOf(target, 'node:workdir:README.md')!.click();
    await settle();
    const status = target.querySelector('[role="status"]');
    expect(status?.textContent?.trim()).toBe('this file could not be opened: no session to open it in');
    expect(status?.classList.contains('files-status--error')).toBe(true);
    expect(legacy).not.toHaveBeenCalled();
  });
});

describe('the view', () => {
  test('starts at the top of its box: the filter row is its first line, with no header or footer of its own', async () => {
    const target = draw();
    await settle();
    const body = target.querySelector('[data-files]')!;
    expect(body.firstElementChild?.hasAttribute('data-files-filter')).toBe(true);
    expect(target.querySelectorAll('button[aria-label*="close" i], [aria-haspopup]')).toHaveLength(0);
  });

  test('the filter asks the find route and draws its answer, and its text is remembered', async () => {
    const target = draw();
    await settle();
    const input = target.querySelector<HTMLInputElement>('[data-files-filter] input[data-field]')!;
    input.value = 'READ';
    input.dispatchEvent(new Event('input', { bubbles: true }));
    await settle(260);
    expect(fake.findIn).toContainEqual(['workdir', '/work/api', 'READ']);
    expect(rowOf(target, 'node:workdir:README.md')).not.toBeNull();
    expect(rowOf(target, 'node:workdir:src')).toBeNull();
    expect(localStorage.getItem(stateKey('core.files', 'filter'))).toBe('READ');
  });

  test('just changes lists the changed files alone, from the chip, and is remembered', async () => {
    const target = draw();
    await settle();
    const chip = target.querySelector<HTMLButtonElement>('[data-files-chip]')!;
    expect(chip.textContent).toBe('changed 1');
    chip.click();
    flushSync();
    expect(chip.getAttribute('aria-pressed')).toBe('true');
    expect(rowOf(target, 'change:src/index.ts:.M')).not.toBeNull();
    expect(rowOf(target, 'node:workdir:README.md')).toBeNull();
    expect(rowOf(target, 'section:user')).toBeNull();
    expect(localStorage.getItem(stateKey('core.files', 'just-changes'))).toBe('true');
  });

  test('an open folder is remembered across a remount and read again', async () => {
    const first = draw();
    await settle();
    rowOf(first, 'node:workdir:src')!.click();
    await settle();
    expect(rowOf(first, 'node:workdir:src/index.ts')).not.toBeNull();
    for (const app of apps) unmount(app, { outro: false });
    apps = [];
    fake.readLevel = [];
    const again = draw();
    await settle();
    expect(rowOf(again, 'node:workdir:src')?.getAttribute('aria-expanded')).toBe('true');
    expect(fake.readLevel).toContainEqual(['workdir', '/work/api', 'src']);
    expect(rowOf(again, 'node:workdir:src/index.ts')).not.toBeNull();
  });
});

describe('the session it shows', () => {
  test('follows the session its host hands it', async () => {
    const target = draw({ scope: { sessionId: 'ses_2', rowId: 2, workingDir: '/work/web', projectId: null } });
    await settle();
    expect(fake.readLevel).toContainEqual(['workdir', '/work/web', '']);
    expect(target.querySelector('[data-files]')?.getAttribute('data-session')).toBe('ses_2');
  });

  test('with no session says so in the project section and still lists the global folder', async () => {
    const target = draw({ scope: null });
    await settle();
    expect(rowOf(target, 'note:workdir:no_session')?.textContent).toContain('pick a session to see its project files');
    expect(rowOf(target, 'node:user:CLAUDE.md')).not.toBeNull();
    expect(fake.readLevel.some(([root]) => root === 'workdir')).toBe(false);
  });
});

describe('the one widget menu', () => {
  test('the definition declares the actions of the menu map, in order', () => {
    expect(FILES_WIDGET.actions.map((action) => action.id)).toEqual([
      'open-path', 'search', 'just-changes', 'whole-file', 'show-global-folder', 'list-project-first', 'include-dot-files', 'git-ignored-files', 'collapse-all', 'reload',
    ]);
  });

  test('the visible path action opens a pasted file with no selected session', async () => {
    const target = draw({ scope: null });
    await settle();
    target.querySelector<HTMLButtonElement>('[data-files-open-path]')!.click();
    flushSync();
    const field = document.querySelector<HTMLInputElement>('.files-path-form input')!;
    field.value = '"/tmp/a.markdown"';
    field.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
    document.querySelector<HTMLFormElement>('.files-path-form')!.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
    await settle();
    expect(fake.paths).toContain('"/tmp/a.markdown"');
  });

  test('under a host the actions reach its menu and run on this copy; the chip goes up into a drawn header', async () => {
    const target = draw({ hostId: 'files-host', drawn: true }, true);
    await settle();
    expect(target.querySelector('[data-test-header] [data-files-chip]')).not.toBeNull();
    expect(target.querySelector('[data-files-filter] [data-files-chip]')).toBeNull();
    const menu = declaredActionsFor('files-host');
    expect(menu.map((action) => action.id)).toEqual(FILES_WIDGET.actions.map((action) => action.id));
    menu.find((action) => action.id === 'include-dot-files')!.run();
    expect(localStorage.getItem(stateKey('core.files', 'dot-files'))).toBe('false');
  });
});
