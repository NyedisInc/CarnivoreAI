/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const api = vi.hoisted(() => ({
  labStatus: vi.fn(), runCapture: vi.fn(), fitTableState: vi.fn(), startMatrix: vi.fn(),
  draftApi: { list: vi.fn(), file: vi.fn(), putFile: vi.fn(), create: vi.fn(), build: vi.fn(), ticket: vi.fn(), handToClaude: vi.fn(), discard: vi.fn() },
}));
vi.mock('./lab-api', async (importOriginal) => ({ ...(await importOriginal<typeof import('./lab-api')>()), ...api }));

import LabMenu from './LabMenu.svelte';
import LabViewer from './LabViewer.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';
import { installLabBus } from './lab-test-bus';
import { pickOption } from './lab-test-dropdown';
import type { DraftSummary } from './drafts-model';

setLocale('en');

const PAGE = '/api/v1/cplugs/devwidgetlab/draft-harness/ticket-one/index.html';
const BUILD_NONE = { state: 'none' as const, sha: null, built_at: null, log: null, error: '' };
const REVISION: DraftSummary = {
  slug: 'notes-denser', kind: 'revision', widget: 'core.notes', title: 'Notes denser', created: '2026-10-18T10:00:00', state: 'built', base_sha: 'abc', session: null,
  files: ['web/src/opscenter/cells/notes/Cell.svelte'], build: { state: 'built', sha: 'abc', built_at: '2026-10-18T10:05:00', log: '/x/build.log', error: '' }, manifest: null, stale: false,
  build_stale: false, code: { app: 'abc', build: 'abc', source: 'abc' },
};
const NEW: DraftSummary = {
  slug: 'pulse-board', kind: 'new', widget: 'core.pulse-board', title: 'Pulse board', created: '2026-10-18T11:00:00', state: 'built', base_sha: 'abc', session: 'ses_1',
  files: [], build: { state: 'built', sha: 'abc', built_at: '2026-10-18T11:05:00', log: null, error: '' },
  manifest: { id: 'core.pulse-board', slot: 'pulse-board', title: 'Pulse board', hosts: ['home', 'terminal'], fits: { sizes: ['small', 'wide'] }, cell: { minPx: 220, minHeight: 88 }, category: 'monitoring' },
  stale: false, build_stale: false, code: { app: 'abc', build: 'abc', source: 'abc' },
};

const mounted: ReturnType<typeof mount>[] = [];

/** Let promises, channel microtasks and effects settle. */
async function settle(): Promise<void> {
  for (let i = 0; i < 10; i += 1) {
    await Promise.resolve();
    await tick();
    flushSync();
  }
}

async function openBoth(): Promise<{ menu: HTMLElement; view: HTMLElement }> {
  const menu = document.body.appendChild(document.createElement('div'));
  const view = document.body.appendChild(document.createElement('div'));
  mounted.push(mount(LabMenu, { target: menu }));
  mounted.push(mount(LabViewer, { target: view }));
  await settle();
  return { menu, view };
}

const button = (root: HTMLElement, text: string) => [...root.querySelectorAll<HTMLButtonElement>('button')].find((b) => b.textContent?.trim() === text)!;
const row = (root: HTMLElement, slug: string) => root.querySelector<HTMLButtonElement>(`[data-draft-row="${slug}"]`)!;
const pairs = (root: HTMLElement) => [...root.querySelectorAll<HTMLElement>('.dwl-pair')];
const framesIn = (root: Element) => [...root.querySelectorAll<HTMLIFrameElement>('iframe.dwl-frame')];

beforeEach(() => {
  installLabBus();
  api.labStatus.mockResolvedValue({ available: true, reason: '', captures_dir: '/x/captures' });
  api.fitTableState.mockResolvedValue({ available: true, reason: '', running: false, started: null, exit: null, table: null });
  api.draftApi.list.mockResolvedValue({ available: true, reason: '', building: null, drafts: [NEW, REVISION] });
  api.draftApi.ticket.mockResolvedValue({ path: PAGE, expires_in: 3600 });
  for (const call of [api.draftApi.file, api.draftApi.putFile, api.draftApi.create, api.draftApi.build, api.draftApi.handToClaude, api.draftApi.discard]) call.mockReset();
});

afterEach(() => {
  while (mounted.length) unmount(mounted.pop()!);
  document.body.innerHTML = '';
  localStorage.clear();
});

describe('the DRAFTS group', () => {
  it('is the last group of the tree, with each draft named by kind and state', async () => {
    const { menu } = await openBoth();
    const tree = menu.querySelector('.dwl-tree')!;
    const kids = [...tree.children];
    const group = tree.querySelector('[data-group="drafts"]')!;
    const rows = kids.slice(kids.indexOf(group) + 1);
    expect(rows.map((node) => node.getAttribute('data-draft-row') ?? `[${node.getAttribute('data-draft-cat')}]`)).toEqual(
      expect.arrayContaining(['[monitoring]', 'pulse-board', 'notes-denser']),
    );
    expect(rows.some((node) => node.getAttribute('data-draft-cat') === 'other')).toBe(false);
    const heading = (cat: string) => rows.findIndex((node) => node.getAttribute('data-draft-cat') === cat);
    expect(rows[heading('monitoring') + 1]!.getAttribute('data-draft-row')).toBe('pulse-board');
    expect(rows[heading('monitoring')]!.textContent).toBe('monitoring');
    expect(kids.slice(0, kids.indexOf(group)).every((node) => !node.hasAttribute('data-draft-row') && !node.hasAttribute('data-draft-cat'))).toBe(true);
    expect(group.textContent).toMatch(/new items\s*2/);
    expect(row(menu, 'pulse-board').textContent).toMatch(/new\s+Pulse board\s+built/);
    expect(row(menu, 'notes-denser').textContent).toMatch(/rev\s+Notes denser\s+built/);
  });

  it('shows no group and turns the draft keys off, with one sentence, on an install with no checkout', async () => {
    api.draftApi.list.mockResolvedValue({ available: false, reason: 'no_checkout', building: null, drafts: [] });
    const { menu } = await openBoth();
    expect(menu.querySelector('[data-group="drafts"]')).toBeNull();
    expect(menu.querySelector<HTMLButtonElement>('[data-draft-new]')!.disabled).toBe(true);
    expect(menu.querySelector<HTMLButtonElement>('[data-draft-revise]')!.disabled).toBe(true);
    expect(menu.querySelectorAll('.dwl-actions-note').length).toBe(1);
    expect(menu.querySelector('.dwl-actions-note')!.textContent).toContain('source folder');
  });
});

describe('the source folder', () => {
  const NONE = { available: false, reason: 'no_checkout', building: null, drafts: [] };

  it('has no field in the slide-out and does not print the folder: the lab finds it itself and the override lives in Settings', async () => {
    api.draftApi.list.mockResolvedValue({ available: true, reason: '', building: null, drafts: [], source: { root: '/repo', origin: 'auto', setting: '', problems: [] } });
    const { menu } = await openBoth();
    expect([...menu.querySelectorAll('input[type="text"]')].filter((one) => !one.closest('.dwl-search'))).toEqual([]);
    expect(menu.textContent).not.toContain('/repo');
    expect(menu.querySelector<HTMLButtonElement>('[data-draft-new]')!.disabled).toBe(false);
  });

  it('when nothing validates, greys the keys and points to Settings once', async () => {
    api.draftApi.list.mockResolvedValue({ ...NONE, source: { root: '', origin: 'none', setting: '', problems: [] } });
    const { menu } = await openBoth();
    expect(menu.querySelectorAll('.dwl-actions-note').length).toBe(1);
    expect(menu.querySelector('.dwl-actions-note')!.textContent).toBe('no widget lab source folder was found. set one in Settings, under the widget lab plugin.');
    expect(menu.querySelector<HTMLButtonElement>('[data-draft-new]')!.disabled).toBe(true);
  });

  it('names a setting that no longer works, with the reasons', async () => {
    api.draftApi.list.mockResolvedValue({ ...NONE, source: { root: '', origin: 'none', setting: '/x', problems: ['web/node_modules is not installed (run npm ci in web/)'] } });
    const { menu } = await openBoth();
    expect(menu.textContent).toContain('/x');
    expect(menu.textContent).toContain('web/node_modules is not installed');
  });
});

describe('making a draft', () => {
  it('"+ new" asks for a name, creates the draft folder through the route and shows it', async () => {
    api.draftApi.list.mockResolvedValue({ available: true, reason: '', building: null, drafts: [] });
    api.draftApi.create.mockImplementation(async () => {
      api.draftApi.list.mockResolvedValue({ available: true, reason: '', building: null, drafts: [{ ...NEW, state: 'starter', build: BUILD_NONE }] });
      return NEW;
    });
    const { menu } = await openBoth();
    menu.querySelector<HTMLButtonElement>('[data-draft-new]')!.click();
    await settle();
    expect(menu.querySelector('.dwl-form')).not.toBeNull();
    expect(menu.querySelector('.dwl-tree')).toBeNull();
    const create = button(menu, 'create draft');
    expect(create.disabled).toBe(true);
    const name = menu.querySelector<HTMLInputElement>('#dwl-draft-name')!;
    name.value = 'Pulse board';
    name.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(create.disabled).toBe(false);
    create.click();
    await settle();
    expect(api.draftApi.create).toHaveBeenCalledWith(expect.objectContaining({ kind: 'new', name: 'Pulse board', hosts: ['home', 'terminal'], sizes: ['small', 'wide'], category: 'tools' }));
    expect(menu.querySelector('.dwl-form')).toBeNull();
    expect(row(menu, 'pulse-board').getAttribute('aria-current')).toBe('true');
    expect(menu.querySelector('[data-draft="pulse-board"]')).not.toBeNull();
  });

  it('the new-widget form shows a category select of the widget drawer\'s categories, not folded away, and sends the pick', async () => {
    api.draftApi.create.mockResolvedValue(NEW);
    const { menu } = await openBoth();
    menu.querySelector<HTMLButtonElement>('[data-draft-new]')!.click();
    await settle();
    const select = menu.querySelector<HTMLSelectElement>('#dwl-draft-category')!;
    expect(select.closest('details')).toBeNull();
    expect([...select.options].map((o) => o.value)).toEqual(['overview', 'sessions', 'catalog', 'monitoring', 'tools', 'live']);
    select.value = 'monitoring';
    select.dispatchEvent(new Event('change', { bubbles: true }));
    const name = menu.querySelector<HTMLInputElement>('#dwl-draft-name')!;
    name.value = 'Pulse board';
    name.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    button(menu, 'create draft').click();
    await settle();
    expect(api.draftApi.create).toHaveBeenCalledWith(expect.objectContaining({ kind: 'new', category: 'monitoring' }));
  });

  it('"make a revision" sends one field and the context that was on show', async () => {
    api.draftApi.create.mockResolvedValue(REVISION);
    const { menu } = await openBoth();
    menu.querySelector<HTMLButtonElement>('[data-draft-revise]')!.click();
    await settle();
    expect(menu.querySelector('.dwl-form')!.textContent).toContain('revision of core.notes');
    expect(menu.querySelectorAll('.dwl-form textarea').length).toBe(1);
    expect(menu.querySelector('#dwl-draft-name')).toBeNull();
    const what = menu.querySelector<HTMLTextAreaElement>('#dwl-draft-what')!;
    what.value = 'the header wastes a row at sidebar s';
    what.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    button(menu, 'start revision').click();
    await settle();
    const sent = api.draftApi.create.mock.calls[0]![0];
    expect(sent).toMatchObject({ kind: 'revision', widget: 'core.notes', what: 'the header wastes a row at sidebar s' });
    expect(sent.context).toMatchObject({ theme: expect.any(String), fixture: 'data' });
  });

  it('shows the server\'s refusal in the form and keeps what was typed', async () => {
    api.draftApi.create.mockRejectedValue(Object.assign(new Error('x'), { name: 'ApiError' }));
    const { menu } = await openBoth();
    menu.querySelector<HTMLButtonElement>('[data-draft-new]')!.click();
    await settle();
    const name = menu.querySelector<HTMLInputElement>('#dwl-draft-name')!;
    name.value = 'Notes';
    name.dispatchEvent(new Event('input', { bubbles: true }));
    await settle();
    expect(name.value).toBe('Notes');
  });
});

describe('the REVISION section', () => {
  it('opens for a picked draft with build, hand to claude, compare mode and discard, and has no land key', async () => {
    const { menu } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    const panel = menu.querySelector<HTMLElement>('[data-draft="notes-denser"]')!;
    expect(panel).not.toBeNull();
    expect(menu.querySelector('.dwl-sec-label')!.textContent).toBeDefined();
    const labels = [...panel.querySelectorAll('button')].map((b) => b.textContent?.trim());
    expect(labels).toEqual(expect.arrayContaining(['rebuild', 'hand to claude', 'side by side', 'draft only', 'discard draft']));
    expect(labels.some((text) => /land|ship it|merge|publish/i.test(text ?? ''))).toBe(false);
    expect(panel.textContent).toContain('ships through its task manager item and your tick');
    button(panel as HTMLElement, 'rebuild').click();
    button(panel as HTMLElement, 'hand to claude').click();
    await settle();
    expect(api.draftApi.build).toHaveBeenCalledWith('notes-denser');
    expect(api.draftApi.handToClaude).toHaveBeenCalledWith('notes-denser');
  });

  it('discards only after its own confirm', async () => {
    api.draftApi.discard.mockResolvedValue({ discarded: '/x' });
    const { menu } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    button(menu, 'discard draft').click();
    await settle();
    expect(api.draftApi.discard).not.toHaveBeenCalled();
    expect(menu.textContent).toContain('nothing is deleted');
    menu.querySelector<HTMLButtonElement>('[data-draft-discard-yes]')!.click();
    await settle();
    expect(api.draftApi.discard).toHaveBeenCalledWith('notes-denser');
  });

  it('turns capture off for a draft, with the reason', async () => {
    const { menu } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    expect(menu.querySelector('.dwl-foot button')!.hasAttribute('disabled')).toBe(true);
  });
});

describe('the compare view', () => {
  it('frames the current widget beside the draft\'s built page at the same size, theme and fixture', async () => {
    const { menu, view } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    expect(api.draftApi.ticket).toHaveBeenCalledWith('notes-denser');
    const first = pairs(view)[0]!;
    const [current, draft] = framesIn(first);
    expect(current!.getAttribute('src')).toMatch(/^\/static\/dist\/widget-lab\/index\.html\?/);
    expect(draft!.getAttribute('src')).toMatch(new RegExp(`^${PAGE.replace(/\//g, '\\/')}\\?`));
    const q = (frame: HTMLIFrameElement) => Object.fromEntries(new URL(frame.src, 'http://x.test').searchParams);
    expect(q(draft!)).toEqual(q(current!));
    expect(first.querySelector('.dwl-side-cap[data-side="draft"]')!.textContent).toBe('draft');
    expect(first.querySelector('.dwl-side-cap[data-side="current"]')!.textContent).toBe('current');
    expect(view.querySelector('.dwl-compare')).not.toBeNull();
  });

  it('asks for a fresh signed link shortly before the first one runs out (u123-06)', async () => {
    api.draftApi.ticket.mockResolvedValue({ path: PAGE, expires_in: 3600 });
    const { menu } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    expect(api.draftApi.ticket).toHaveBeenCalledTimes(1);
    vi.useFakeTimers({ toFake: ['setTimeout', 'clearTimeout'] });
    try {
      row(menu, 'pulse-board').click();
      await settle();
      row(menu, 'notes-denser').click();
      await settle();
      const asked = api.draftApi.ticket.mock.calls.length;
      await vi.advanceTimersByTimeAsync(3_500_000);
      expect(api.draftApi.ticket).toHaveBeenCalledTimes(asked);
      await vi.advanceTimersByTimeAsync(60_000);
      expect(api.draftApi.ticket.mock.calls.length).toBeGreaterThan(asked);
    } finally {
      vi.useRealTimers();
    }
  });

  it('draws both sides in the host chrome the viewer uses, and one box for the pair: resizing either side resizes both and redraws both frames', async () => {
    const { menu, view } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    const pair = pairs(view).find((one) => one.dataset['host'] === 'home')!;
    expect(pair.querySelectorAll('.dwl-chrome--home')).toHaveLength(2);
    const sides = [...pair.querySelectorAll<HTMLElement>('.dwl-pair-side')];
    const before = framesIn(pair).map((frame) => frame.src);
    const dims = () => [...pair.querySelectorAll('[data-testid="dims"]')].map((one) => one.textContent!.replace(/\s+/g, ' ').trim());
    const handle = sides[1]!.querySelector<HTMLElement>('.dwl-handle--e')!;
    handle.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', shiftKey: true, bubbles: true, cancelable: true }));
    await settle();
    expect(dims()).toHaveLength(1);
    expect(dims()[0]).toMatch(/^\d+ x \d+$/);
    await new Promise((resolve) => setTimeout(resolve, 500));
    await settle();
    const after = framesIn(pair);
    const width = (frame: HTMLIFrameElement) => new URL(frame.src, 'http://x.test').searchParams.get('w');
    expect(after.map(width)).toEqual([width(after[0]!), width(after[0]!)]);
    expect(width(after[0]!)).not.toBeNull();
    expect(after.map((frame) => frame.src)).not.toEqual(before);
    expect(pair.querySelectorAll('[data-reset]')).toHaveLength(1);
    pair.querySelector<HTMLButtonElement>('[data-reset]')!.click();
    await settle();
    expect(framesIn(pair).map(width)).toEqual([null, null]);
  });

  it('draws the right drawer as the real slide-out on both sides, one frame per side at the panel body, each with one inner-edge handle', async () => {
    const { menu, view } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    for (const name of ['left', 'bottom']) {
      pickOption(menu, 'show-in', name);
      await settle();
    }
    const pair = pairs(view).find((one) => one.dataset['host'] === 'drawer')!;
    expect(pair.querySelectorAll('.dwl-dock-panel--side')).toHaveLength(2);
    expect(pair.querySelectorAll('.dwl-handle--w')).toHaveLength(2);
    expect(pair.querySelectorAll('.dwl-handle--e, .dwl-handle--s, .dwl-handle--se')).toHaveLength(0);
    for (const frame of framesIn(pair)) {
      const q = new URL(frame.src, 'http://x.test').searchParams;
      expect([q.get('dock'), q.get('w'), q.get('h')]).toEqual(['side', '378', '800']);
    }
  });

  it('"draft only" shows the draft frame alone', async () => {
    const { menu, view } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    button(menu, 'draft only').click();
    await settle();
    expect(framesIn(pairs(view)[0]!).length).toBe(1);
    expect(framesIn(pairs(view)[0]!)[0]!.getAttribute('src')).toContain('draft-harness');
  });

  it('draws a NEW widget alone in its declared hosts and says there is nothing to compare against', async () => {
    const { menu, view } = await openBoth();
    row(menu, 'pulse-board').click();
    await settle();
    const strip = view.querySelector('.dwl-compare-strip')!;
    expect(strip.textContent).toContain('nothing to compare against');
    expect([...view.querySelectorAll('.dwl-host')].length).toBeGreaterThan(0);
    const all = framesIn(view);
    expect(all.length).toBeGreaterThan(0);
    expect(all.every((frame) => frame.getAttribute('src')!.includes('draft-harness') && new URL(frame.src, 'http://x.test').searchParams.get('widget') === 'core.pulse-board')).toBe(true);
    expect(view.querySelectorAll('.dwl-side-cap[data-side="current"]').length).toBe(0);
  });

  it('says what the draft is doing until it is built', async () => {
    api.draftApi.list.mockResolvedValue({ available: true, reason: '', building: null, drafts: [{ ...REVISION, state: 'failed', build: { ...BUILD_NONE, state: 'failed', error: 'error: boom', log: '/x/build.log' } }] });
    const { menu, view } = await openBoth();
    row(menu, 'notes-denser').click();
    await settle();
    expect(view.querySelector('.dwl-compare-strip')!.textContent).toContain('build failed');
    expect(view.textContent).toContain('error: boom');
    expect(view.textContent).toContain('/x/build.log');
    expect(pairs(view).length).toBe(0);
    expect(api.draftApi.ticket).not.toHaveBeenCalled();
  });
});

describe('"show in" lists all six places', () => {
  const rows = (menu: HTMLElement) => [...menu.querySelectorAll<HTMLElement>('[data-choice="show-in"] [data-choice-option]')];
  const off = (menu: HTMLElement) => rows(menu).filter((one) => one.querySelector('.dwl-pick--off'));

  it('dims a place a new draft does not declare, and ticking it adds the host to widget.json and contract.json through the files route', async () => {
    const files: Record<string, string> = {
      'widget.json': JSON.stringify({ id: 'core.pulse-board', hosts: ['home', 'terminal'] }),
      'contract.json': JSON.stringify({ id: 'core.pulse-board', hosts: ['home', 'terminal'] }),
    };
    api.draftApi.file.mockImplementation(async (_slug: string, path: string) => ({ path, content: files[path] }));
    api.draftApi.putFile.mockResolvedValue({});
    const { menu } = await openBoth();
    row(menu, 'pulse-board').click();
    await settle();
    pickOption(menu, 'show-in', 'home');
    await settle();
    expect(rows(menu)).toHaveLength(6);
    expect(off(menu).map((one) => one.getAttribute('data-choice-option'))).toEqual(['left', 'bottom', 'right', 'popout']);
    expect(off(menu)[0]!.textContent).toContain('not used yet');
    expect(off(menu)[0]!.getAttribute('aria-disabled')).not.toBe('true');
    pickOption(menu, 'show-in', 'popout');
    await settle();
    const written = Object.fromEntries(api.draftApi.putFile.mock.calls.map(([, path, content]) => [path, JSON.parse(content as string)]));
    expect(written['widget.json'].hosts).toEqual(['home', 'terminal', 'popout']);
    expect(written['contract.json'].hosts).toEqual(['home', 'terminal', 'popout']);
    expect(api.draftApi.putFile.mock.calls.every(([slug]) => slug === 'pulse-board')).toBe(true);
    expect(menu.textContent).toContain('added, rebuild the draft');
  });

  it('leaves a shipped widget\'s undeclared place dimmed, titled, and impossible to tick', async () => {
    const { menu } = await openBoth();
    let gone: HTMLElement[] = [];
    for (const group of menu.querySelectorAll<HTMLElement>('[data-group-nested][aria-expanded="false"]')) group.click();
    await settle();
    for (const leaf of [...menu.querySelectorAll<HTMLElement>('[data-tree-leaf][data-key]:not([data-draft-row])')]) {
      leaf.click();
      await settle();
      if (!menu.querySelector('[data-choice="show-in"] [data-choice-list]')) pickOption(menu, 'show-in', 'home');
      await settle();
      gone = off(menu);
      if (gone.length > 0) break;
    }
    expect(rows(menu)).toHaveLength(6);
    expect(gone.length).toBeGreaterThan(0);
    for (const one of gone) {
      expect(one.getAttribute('aria-disabled')).toBe('true');
      expect(one.querySelector('.dwl-pick--off')!.getAttribute('title')).toBe('this widget does not declare this place');
    }
    const id = gone[0]!.getAttribute('data-choice-option')!;
    pickOption(menu, 'show-in', id);
    await settle();
    expect(api.draftApi.putFile).not.toHaveBeenCalled();
    expect(rows(menu).find((one) => one.getAttribute('data-choice-option') === id)!.getAttribute('aria-selected')).not.toBe('true');
  });
});
