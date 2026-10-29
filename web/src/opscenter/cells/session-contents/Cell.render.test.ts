/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls = vi.hoisted(() => [] as string[]);
const reply = vi.hoisted(() => ({ fail: null as null | { status: number; code: string }, gates: {} as Record<string, Promise<void>> }));
const opened = vi.hoisted(() => [] as Record<string, unknown>[]);
const reads = vi.hoisted(() => [] as string[]);
const readReply = vi.hoisted(() => ({ sensitive: false }));

function one(name: string, scope: string, path: string | null, more: Record<string, unknown> = {}): Record<string, unknown> {
  return { name, scope, path, description: '', detail: '', lines: null, open_root: null, open_path: null, status: 'available', ...more };
}

function answerFor(rowId: number): unknown {
  return {
    session_uuid: `uuid-${rowId}`, row_id: rowId, family: 'claude', config_dir: `/accts/joe-imc`, working_dir: '/work/p',
    sections: [
      { kind: 'instructions', truncated: false, items: [
        one('CLAUDE.md', 'global', '/cfg/CLAUDE.md', { lines: 63, open_root: 'user', open_path: 'CLAUDE.md', status: 'loaded' }),
        one('rules/git.md', 'project', '/work/p/.claude/rules/git.md', { lines: 19, detail: '19 lines', open_root: 'workdir', open_path: '.claude/rules/git.md', status: 'loaded' })] },
      { kind: 'skills', truncated: false, items: [
        one(`skill-${rowId}`, 'global', '/cfg/skills/a/SKILL.md', { description: 'does a thing', lines: 5, open_root: 'user', open_path: 'skills/a/SKILL.md' }),
        one('pdf', 'plugin', '/plug/skills/pdf/SKILL.md', { description: 'fills pdfs', lines: 7 })] },
      { kind: 'mcp', truncated: false, items: [one('gh', 'global', '/home/.claude.json', { detail: 'stdio npx', status: 'loaded' })] },
      { kind: 'plugins', truncated: false, items: [] },
    ],
  };
}

vi.mock('../../../lib/open-files/open-bridge', () => ({
  openFromDrawer: async (request: Record<string, unknown>) => { opened.push(request); return 'opened'; },
}));

vi.mock('../../api/auth.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../api/auth.svelte')>();
  return {
    ...real,
    authFetch: async (path: string) => {
      if (path.startsWith('/config-files/read')) {
        reads.push(path);
        return { content: Array.from({ length: 12 }, (_, i) => `line ${i + 1}`).join('\n'), is_sensitive: readReply.sensitive };
      }
      calls.push(path);
      if (reply.gates[path]) await reply.gates[path];
      if (reply.fail) throw new real.ApiError('refused', reply.fail.status, reply.fail.code);
      return answerFor(Number(path.split('/')[2]));
    },
  };
});

vi.mock('../../shell/frame-header.svelte', async (importOriginal) => {
  const real = await importOriginal<typeof import('../../shell/frame-header.svelte')>();
  return { ...real, useFrameHeader: () => ({ hostId: 'sc-host', takesBars: false }) };
});

import Cell from './Cell.svelte';
import { declaredActionsFor } from '../../widgets/menu/declared-actions.svelte';
import { ContentsStore, acquireContents } from './state.svelte';
import { metaFor } from '../../engine/meta';
import { setLocale } from '../../../lib/i18n/index.svelte';

setLocale('en');

let app: ReturnType<typeof mount> | null = null;
let host: HTMLElement;

async function settle(): Promise<void> {
  for (let i = 0; i < 12; i += 1) { await Promise.resolve(); await tick(); }
  flushSync();
}

async function draw(rowId: number | null, extra: Record<string, unknown> = {}): Promise<void> {
  const scope = rowId === null ? null : { sessionId: `ses_${rowId}`, rowId, workingDir: '/work/p', projectId: null };
  app = mount(Cell, { target: host, props: { width: 380, height: 600, meta: metaFor('session-contents'), instance: 'sc', scope, ...extra } });
  await settle();
}

beforeEach(() => {
  calls.length = 0;
  reply.fail = null;
  reply.gates = {};
  opened.length = 0;
  reads.length = 0;
  readReply.sensitive = false;
  try { localStorage.clear(); } catch {  }
  host = document.createElement('div');
  document.body.appendChild(host);
});
afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
  vi.useRealTimers();
});

const sectionOf = (kind: string): HTMLElement => host.querySelector<HTMLElement>(`[data-kind="${kind}"]`)!;
const names = (kind: string): (string | null)[] => [...sectionOf(kind).querySelectorAll('[data-sc-name]')].map((el) => el.textContent);
const click = async (el: Element | null): Promise<void> => { (el as HTMLElement).click(); await settle(); };

describe('the resources', () => {
  test('lists every section with its count; only the instruction files start open', async () => {
    await draw(7);
    expect(calls).toEqual(['/sessions/7/contents']);
    expect([...host.querySelectorAll('.oc-fold__label')].map((el) => el.textContent)).toEqual(['instruction files', 'skills', 'mcp servers', 'plugins']);
    expect(sectionOf('skills').querySelector('.oc-fold__count')?.textContent).toBe('2');
    expect(names('instructions')).toEqual(['CLAUDE.md', 'rules/git.md']);
    expect(sectionOf('skills').querySelectorAll('[data-sc-row]')).toHaveLength(0);
    expect(host.querySelector('.sc-sub__who')?.textContent).toBe('claude joe-imc');
  });

  test('a row starts with a scope icon that has its own tooltip and label, and no scope letter is printed', async () => {
    await draw(7);
    await click(sectionOf('skills').querySelector('.oc-fold__toggle'));
    const icons = (kind: string): string[][] => [...sectionOf(kind).querySelectorAll('[data-sc-scope-icon]')].map((el) =>
      [el.querySelector('svg')!.getAttribute('data-icon')!, el.getAttribute('aria-label')!, el.getAttribute('title')!]);
    expect(icons('instructions')).toEqual([['globe', 'global', 'global'], ['folder', 'project', 'project']]);
    expect(icons('skills')).toEqual([['globe', 'global', 'global'], ['plug', 'plugin', 'plugin']]);
    expect(host.querySelector('[data-sc-meta]')).toBeNull();
    expect(host.textContent).not.toContain('PL');
  });

  test('the line count reads "19 lines" with a short "19L" beside it for a narrow row, and no dot; a row with no lines shows neither', async () => {
    await draw(7);
    const rows = [...sectionOf('instructions').querySelectorAll('[data-sc-lines]')];
    expect(rows.map((el) => el.querySelector('[data-sc-lines-long]')?.textContent)).toEqual(['63 lines', '19 lines']);
    expect(rows.map((el) => el.querySelector('[data-sc-lines-short]')?.textContent)).toEqual(['63L', '19L']);
    expect(rows.every((el) => !(el.textContent ?? '').includes('·'))).toBe(true);
    await click(sectionOf('mcp').querySelector('.oc-fold__toggle'));
    expect(sectionOf('mcp').querySelector('[data-sc-lines]')).toBeNull();
    expect(host.textContent).not.toContain('·');
  });

  test('a section header folds and opens its rows', async () => {
    await draw(7);
    await click(sectionOf('skills').querySelector('.oc-fold__toggle'));
    expect(names('skills')).toEqual(['skill-7', 'pdf']);
    await click(sectionOf('instructions').querySelector('.oc-fold__toggle'));
    expect(sectionOf('instructions').querySelectorAll('[data-sc-row]')).toHaveLength(0);
  });

  test('show path swaps each name for its path', async () => {
    await draw(7);
    const key = host.querySelector<HTMLElement>('[data-sc-path-toggle]')!;
    expect(key.getAttribute('aria-label')).toBe('show path');
    expect(key.getAttribute('title')).toBe('show path');
    expect(key.getAttribute('aria-pressed')).toBe('false');
    await click(key);
    expect(names('instructions')).toEqual(['/cfg/CLAUDE.md', '/work/p/.claude/rules/git.md']);
    expect(host.querySelector('[data-sc-path-toggle]')?.getAttribute('aria-pressed')).toBe('true');
    expect(host.querySelectorAll('.sc-sub [data-sc-path-toggle]')).toHaveLength(1);
  });

  test('no session says so and reads nothing', async () => {
    await draw(null);
    expect(calls).toEqual([]);
    expect(host.querySelector('.sc-cell .oc-state__title')?.textContent).toBe('select a session to see what it has loaded.');
  });
});

describe('the filter box', () => {
  test('narrows the expanded sections by name, path or description, case blind', async () => {
    await draw(7);
    await click(sectionOf('skills').querySelector('.oc-fold__toggle'));
    const box = host.querySelector<HTMLInputElement>('[data-sc-filter]')!;
    box.value = 'GIT';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(names('instructions')).toEqual(['rules/git.md']);
    expect(sectionOf('instructions').querySelector('.oc-fold__count')?.textContent).toBe('1');
    expect(names('skills')).toEqual([]);
    box.value = 'fills';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(names('skills')).toEqual(['pdf']);
  });
});

describe('the scope option group', () => {
  const group = (): HTMLElement => host.querySelector<HTMLElement>('[data-sc-scopes]')!;
  const option = (name: string): HTMLElement => group().querySelector<HTMLElement>(`[data-sc-scope="${name}"]`)!;
  const active = (): string[] => [...group().querySelectorAll('[aria-checked="true"]')].map((el) => el.getAttribute('data-sc-scope')!);

  test('is a radio group of three icon options, each with a tooltip and label, one active', async () => {
    await draw(7);
    expect(group().getAttribute('role')).toBe('radiogroup');
    expect([...group().querySelectorAll('[role="radio"]')].map((el) => el.querySelector('svg')!.getAttribute('data-icon'))).toEqual(['folder', 'globe', 'list']);
    expect(option('local').getAttribute('title')).toBe('local (this project)');
    expect(option('global').getAttribute('aria-label')).toBe('global (the account)');
    expect(option('all').getAttribute('title')).toBe('all');
    expect(active()).toEqual(['all']);
    expect(host.querySelector('.sc-scope')).toBeNull();
  });

  test('choosing an option filters the rows; a plugin counts as global', async () => {
    await draw(7);
    await click(sectionOf('skills').querySelector('.oc-fold__toggle'));
    await click(option('local'));
    expect(active()).toEqual(['local']);
    expect(names('instructions')).toEqual(['rules/git.md']);
    expect(names('skills')).toEqual([]);
    await click(option('global'));
    expect(active()).toEqual(['global']);
    expect(names('instructions')).toEqual(['CLAUDE.md']);
    expect(names('skills')).toEqual(['skill-7', 'pdf']);
    await click(option('all'));
    expect(active()).toEqual(['all']);
  });

  test('a host that keeps options stores the choice on the copy and reads it back', async () => {
    const written: [string, unknown][] = [];
    await draw(7, { options: { scope: 'local' }, onOption: (k: string, v: unknown) => written.push([k, v]) });
    expect(active()).toEqual(['local']);
    await click(option('global'));
    expect(written).toEqual([['scope', 'global']]);
  });

  test('a host with no option writer remembers it per device and per copy', async () => {
    await draw(7);
    await click(option('local'));
    expect(localStorage.getItem('cloude_session_resources_scope_sc')).toBe('local');
    unmount(app!);
    app = null;
    host.innerHTML = '';
    await draw(7);
    expect(active()).toEqual(['local']);
  });
});

describe('empty sections', () => {
  const toggle = (): HTMLElement => host.querySelector<HTMLElement>('[data-sc-empty-toggle]')!;
  const kinds = (): (string | null)[] => [...host.querySelectorAll('.oc-fold__label')].map((el) => el.textContent);

  test('show by default; the title bar key hides the sections that read 0 and shows them again', async () => {
    await draw(7);
    expect(toggle().getAttribute('aria-pressed')).toBe('true');
    expect(toggle().getAttribute('title')).toBe('show empty sections');
    expect(kinds()).toContain('plugins');
    await click(toggle());
    expect(toggle().getAttribute('aria-pressed')).toBe('false');
    expect(toggle().querySelector('svg')?.getAttribute('data-icon')).toBe('folder-eye-off');
    expect(kinds()).toEqual(['instruction files', 'skills', 'mcp servers']);
    await click(toggle());
    expect(kinds()).toContain('plugins');
  });

  test('with filter text, hiding also drops the sections the text emptied', async () => {
    await draw(7);
    const box = host.querySelector<HTMLInputElement>('[data-sc-filter]')!;
    box.value = 'git';
    box.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(kinds()).toEqual(['instruction files', 'skills', 'mcp servers', 'plugins']);
    await click(toggle());
    expect(kinds()).toEqual(['instruction files']);
  });

  test('the menu item does the same, and the choice is stored on the copy through the option writer', async () => {
    const written: [string, unknown][] = [];
    await draw(7, { options: { show_empty: false }, onOption: (k: string, v: unknown) => written.push([k, v]) });
    expect(kinds()).not.toContain('plugins');
    const item = declaredActionsFor('sc-host').find((a) => a.id === 'show-empty')!;
    expect(item.checked).toBe(false);
    item.run();
    expect(written).toEqual([['show_empty', true]]);
  });

  test('a host with no option writer remembers it per device and per copy', async () => {
    await draw(7);
    await click(toggle());
    expect(localStorage.getItem('cloude_session_resources_empty_sc')).toBe('hide');
    unmount(app!);
    app = null;
    host.innerHTML = '';
    await draw(7);
    expect(kinds()).not.toContain('plugins');
  });
});

describe('selecting and opening', () => {
  const rowsOf = (kind: string): HTMLElement[] => [...sectionOf(kind).querySelectorAll<HTMLElement>('[data-sc-row]')];

  test('a press on a row selects it and shows its details, and opens nothing', async () => {
    await draw(7);
    await click(rowsOf('instructions')[1]!.querySelector('[data-sc-main]'));
    expect(opened).toEqual([]);
    expect(rowsOf('instructions')[1]!.hasAttribute('data-selected')).toBe(true);
    const details = host.querySelector('[data-sc-details]')!.textContent ?? '';
    expect(details).toContain('rules/git.md');
    expect(details).toContain('project');
    expect(details).toContain('19 lines, instruction file');
    expect(details.match(/19 lines/g)).toHaveLength(1);
    expect(details).toContain('/work/p/.claude/rules/git.md');
    expect(details).toContain('load status: loaded');
    expect(host.querySelector('.sc-strip')?.textContent).toContain('lines ≠ context tokens');
  });

  test('the short "19L" rule keys on the row container at a 310px row (jsdom has no container queries, so the rule is checked in the source)', async () => {
    const source = readFileSync(`${process.cwd()}/src/opscenter/cells/session-contents/Cell.svelte`, 'utf8');
    expect(source).toMatch(/\.sc-row__body \{[^}]*container: oc-sc-row \/ inline-size;/);
    expect(source).toMatch(/@container oc-sc-row \(max-width: 310px\) \{[^}]*\.sc-row__lines-long \{ display: none; \}[^}]*\.sc-row__lines-short \{ display: inline; \}/);
    expect(source).toMatch(/<ListRow density="dense"/);
  });

  test('the open key is on file rows only and is the only thing that opens the file in the Files tab', async () => {
    await draw(7);
    await click(sectionOf('mcp').querySelector('.oc-fold__toggle'));
    expect(rowsOf('instructions').map((row) => row.querySelector('[data-sc-open]') !== null)).toEqual([true, true]);
    expect(rowsOf('mcp').map((row) => row.querySelector('[data-sc-open]'))).toEqual([null]);
    const key = rowsOf('instructions')[1]!.querySelector<HTMLElement>('[data-sc-open]')!;
    expect(key.querySelector('svg')?.getAttribute('data-icon')).toBe('files');
    expect(key.getAttribute('aria-label')).toBe('open rules/git.md in the files tab');
    expect(key.getAttribute('title')).toBe('open rules/git.md in the files tab');
    await click(key);
    expect(opened).toEqual([{ sessionId: 'ses_7', sessionRowId: 7, root: 'workdir', path: '.claude/rules/git.md' }]);
  });

  test('an item with no file selects, has no open key and opens nothing', async () => {
    await draw(7);
    await click(sectionOf('mcp').querySelector('.oc-fold__toggle'));
    await click(sectionOf('mcp').querySelector('[data-sc-main]'));
    expect(opened).toEqual([]);
    expect(host.querySelector('[data-sc-details]')?.textContent).toContain('no file to open');
  });

  test('nothing selected says where the details will appear', async () => {
    await draw(7);
    expect(host.querySelector('[data-sc-details]')?.textContent).toContain('full source path and load status appear here.');
  });
});

describe('the head preview', () => {
  const pick = async (kind: string, index: number): Promise<void> => click(sectionOf(kind).querySelectorAll('[data-sc-main]')[index] ?? null);

  test('a prose file shows its first eight lines in the details, read through the guarded read route', async () => {
    await draw(7);
    await pick('instructions', 1);
    expect(reads).toEqual(['/config-files/read?root=workdir&path=.claude%2Frules%2Fgit.md&project_path=%2Fwork%2Fp']);
    expect(host.querySelector('[data-sc-head]')?.textContent).toBe(Array.from({ length: 8 }, (_, i) => `line ${i + 1}`).join('\n'));
  });

  test('a file the server flags sensitive shows no preview', async () => {
    readReply.sensitive = true;
    await draw(7);
    await pick('instructions', 0);
    expect(reads).toHaveLength(1);
    expect(host.querySelector('[data-sc-head]')).toBeNull();
  });

  test('a kind that holds keys or env values is never read', async () => {
    await draw(7);
    await click(sectionOf('mcp').querySelector('.oc-fold__toggle'));
    await pick('mcp', 0);
    expect(reads).toEqual([]);
    expect(host.querySelector('[data-sc-head]')).toBeNull();
  });
});

describe('the widget menu', () => {
  test('declares the scope choices, the empty sections and show path ticks, and refresh on the frame slot', async () => {
    await draw(7);
    const actions = declaredActionsFor('sc-host');
    expect(actions.map((a) => a.id)).toEqual(['scope:local', 'scope:global', 'scope:all', 'show-empty', 'show-path', 'refresh']);
    expect(actions.filter((a) => a.checked && !a.toggle).map((a) => a.id)).toEqual(['scope:all']);
    actions.find((a) => a.id === 'scope:global')!.run();
    await settle();
    expect(declaredActionsFor('sc-host').find((a) => a.id === 'scope:global')?.checked).toBe(true);
    declaredActionsFor('sc-host').find((a) => a.id === 'show-path')!.run();
    await settle();
    expect(names('instructions')[0]).toBe('/cfg/CLAUDE.md');
    declaredActionsFor('sc-host').find((a) => a.id === 'refresh')!.run();
    await settle();
    expect(calls).toHaveLength(2);
  });
});

describe('push, not poll', () => {
  test('there is no timer: minutes pass and nothing is read again', async () => {
    vi.useFakeTimers();
    await draw(7);
    vi.advanceTimersByTime(30 * 60 * 1000);
    await settle();
    expect(calls).toHaveLength(1);
  });

  test('the refresh key reads again, and a new session reads its own row', async () => {
    await draw(7);
    host.querySelector<HTMLButtonElement>('[data-sc-refresh]')!.click();
    await settle();
    expect(calls).toEqual(['/sessions/7/contents', '/sessions/7/contents']);
    await unmount(app!);
    app = null;
    await draw(8);
    expect(calls.at(-1)).toBe('/sessions/8/contents');
  });

  test('a slow reply for the old session never paints over the new one', async () => {
    let release!: () => void;
    reply.gates['/sessions/1/contents'] = new Promise<void>((resolve) => { release = resolve; });
    const contents = new ContentsStore();
    contents.follow(1);
    contents.follow(2);
    await settle();
    expect(contents.data?.row_id).toBe(2);
    release();
    await settle();
    expect(contents.data?.row_id).toBe(2);
  });
});

describe('refusals', () => {
  test('a paired computer session is worded, not a bare error', async () => {
    reply.fail = { status: 409, code: 'remote_host' };
    await draw(7);
    expect(host.querySelector('.sc-cell .oc-state__title')?.textContent).toBe('this session runs on a paired computer; open its contents there.');
  });

  test('an unknown failure uses the generic line', async () => {
    reply.fail = { status: 500, code: 'boom' };
    await draw(7);
    expect(host.querySelector('.sc-cell .oc-state__title')?.textContent).toBe("could not read this session's files.");
  });
});

describe('u158-03: one store per followed row', () => {
  test('two widgets on different rows each keep their own answer; the same row shares one read', async () => {
    const a = acquireContents(1);
    const b = acquireContents(2);
    const again = acquireContents(1);
    await settle();
    expect(a.store).not.toBe(b.store);
    expect(a.store).toBe(again.store);
    expect(a.store.data?.row_id).toBe(1);
    expect(b.store.data?.row_id).toBe(2);
    a.release(); again.release(); b.release();
  });
});
