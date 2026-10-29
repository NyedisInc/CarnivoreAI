/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls = vi.hoisted(() => ({ list: [] as { path: string; init?: RequestInit }[], next: [] as unknown[] }));
vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
  return {
    ...actual,
    authFetch: async (path: string, init?: RequestInit) => {
      calls.list.push({ path, init });
      const answer = calls.next.shift();
      if (answer instanceof Error) throw answer;
      return answer;
    },
  };
});

import DashboardsScreen from './DashboardsScreen.svelte';
import { dashboardsUi } from './dashboard-actions.svelte';
import { boardShape } from './board-shape';
import { dashboardOpensEditing } from '../../popout/popout';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const OPSCENTER = path.join(path.dirname(fileURLToPath(import.meta.url)), '..', '..', 'opscenter');
const pageCss = readFileSync(path.join(OPSCENTER, 'page.css'), 'utf8');
const tokensCss = readFileSync(path.join(OPSCENTER, 'tokens.css'), 'utf8');
import { ApiError } from '../../opscenter/api/auth.svelte';
import { homeBoards } from '../../opscenter/engine/home-sync.svelte';
import { RAIL_DESTINATIONS } from '../../opscenter/shell/rail-items';
let app: ReturnType<typeof mount> | null = null;

const preview = { name: 'ops', widgets: ['projects'], settings: [], drawer_zone: [], refusals: [], ok: true };
const body = (call: { init?: RequestInit }) => JSON.parse(String(call.init?.body));

async function pick(content: string): Promise<void> {
  const input = document.querySelector<HTMLInputElement>('[data-board-import-file]')!;
  const file = new File([content], 'x.carnivore-board.json', { type: 'application/json' });
  (file as { text?: () => Promise<string> }).text = async () => content;
  Object.defineProperty(input, 'files', { value: [file], configurable: true });
  input.dispatchEvent(new Event('change', { bubbles: true }));
  for (let i = 0; i < 5; i++) await tick();
  flushSync();
}

beforeEach(() => {
  calls.list = [];
  calls.next = [];
  dashboardsUi.notice = '';
  dashboardsUi.busy = false;
  homeBoards.list = [{ id: 'b2', name: 'wall' }, { id: 'home', name: 'ops' }] as never;
  homeBoards.layouts = {
    b2: { v: 6, hidden: [], rows: [
      { id: 'r1', kind: 'px', size: 280, slots: [{ id: 'projects', fr: 2 }, { id: 'notes', fr: 1 }] },
      { id: 'r2', kind: 'flex', size: 1, slots: [{ id: 'running-sessions', fr: 1 }] },
    ] },
  } as never;
  homeBoards.active = 'home';
  app = mount(DashboardsScreen, { target: document.body, props: { embedded: true } });
  flushSync();
});

afterEach(() => {
  if (app) unmount(app);
  app = null;
  document.body.innerHTML = '';
});

const row = (id: string) => document.querySelector(`[data-dashboard="${id}"]`)!;
const settle = async () => {
  for (let i = 0; i < 5; i++) await tick();
  flushSync();
};

test('dashboards are the first menu row and the home row is gone (Alex (Example-owner), 2026-10-14)', () => {
  const ids = RAIL_DESTINATIONS.map((item) => item.id);
  expect(ids[0]).toBe('dashboards');
  expect(ids).not.toContain('home');
});

test('the active dashboard is marked and can be neither deleted nor re-activated', () => {
  expect(row('home').querySelector('[data-dashboard-active]')).not.toBeNull();
  expect(row('home').querySelector('[data-dashboard-delete]')).toBeNull();
  expect(row('home').querySelector('[data-dashboard-activate]')).toBeNull();
  expect(row('b2').querySelector('[data-dashboard-delete]')).not.toBeNull();
});

test('new posts a dashboard without activating it', async () => {
  calls.next = [{ dashboards: [], active: 'home', revision: 2, synced: true, created: 'b3' }];
  document.querySelector<HTMLButtonElement>('[data-dashboard-new]')!.click();
  await settle();
  expect(calls.list[0]!.path).toBe('/dashboards');
  expect(calls.list[0]!.init?.method).toBe('POST');
  expect(body(calls.list[0]!).name).toBe('dashboard 3');
  expect(body(calls.list[0]!).layout.v).toBeTypeOf('number');
  expect(calls.list.some((call) => call.path.endsWith('/activate'))).toBe(false);
});

test('set active calls the activate route', async () => {
  calls.next = [{ dashboards: [], active: 'b2', revision: 2, synced: true }];
  row('b2').querySelector<HTMLButtonElement>('[data-dashboard-activate]')!.click();
  await settle();
  expect(calls.list[0]!.path).toBe('/dashboards/b2/activate');
  expect(calls.list[0]!.init?.method).toBe('POST');
});

test('delete waits for the danger confirm', async () => {
  row('b2').querySelector<HTMLButtonElement>('[data-dashboard-delete]')!.click();
  flushSync();
  expect(calls.list).toHaveLength(0);
  const go = row('b2').querySelector<HTMLButtonElement>('[data-dashboard-delete-confirm]')!;
  expect(go.getAttribute('data-btn')).toBe('danger');
  calls.next = [{ dashboards: [], active: 'home', revision: 3, synced: true }];
  go.click();
  await settle();
  expect(calls.list[0]!.path).toBe('/dashboards/b2');
  expect(calls.list[0]!.init?.method).toBe('DELETE');
});

test('a refusal is said in the status line', async () => {
  calls.next = [new ApiError('this dashboard is the home screen', 409, 'dashboard_active')];
  row('b2').querySelector<HTMLButtonElement>('[data-dashboard-delete]')!.click();
  flushSync();
  row('b2').querySelector<HTMLButtonElement>('[data-dashboard-delete-confirm]')!.click();
  await settle();
  expect(document.querySelector('[data-dashboards-status]')!.textContent).toContain('home screen');
});

test('edit puts a non-active dashboard in its own edit pop-out', () => {
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  row('b2').querySelector<HTMLButtonElement>('[data-dashboard-edit]')!.click();
  expect(open).toHaveBeenCalledOnce();
  expect(String(open.mock.calls[0]![0])).toContain('/static/popout.html?board=b2&edit=1');
  expect(open.mock.calls[0]![1]).toBe('carnivore-dashboard-b2');
});

test('open shows a non-active dashboard in the main area, not a new window', () => {
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  row('b2').querySelector<HTMLButtonElement>('[data-dashboard-open]')!.click();
  expect(open).not.toHaveBeenCalled();
});

test('export calls the export route and starts a download', async () => {
  URL.createObjectURL = vi.fn(() => 'blob:x');
  URL.revokeObjectURL = vi.fn();
  const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
  calls.next = [{ format: 'carnivore-board', version: 1 }];
  document.querySelector<HTMLButtonElement>('[data-dashboard="home"] [data-dashboard-export]')!.click();
  for (let i = 0; i < 5; i++) await tick();
  expect(calls.list[0]!.path).toBe('/boards/home/export');
  expect(click).toHaveBeenCalledOnce();
});

test('a refused file lists every reason and offers no confirm', async () => {
  calls.next = [new ApiError('first', 400, 'board_refused', { detail: { refusals: ['a is not a widget', 'b does not fit'] } })];
  await pick('{"format":"carnivore-board"}');
  expect(body(calls.list[0]!).dry_run).toBe(true);
  const text = document.querySelector('[data-board-import-problem]')!.textContent!;
  expect(text).toContain('a is not a widget');
  expect(text).toContain('b does not fit');
  expect(document.querySelector('[data-board-import-confirm]')).toBeNull();
});

test('a previewed file imports only on confirm', async () => {
  calls.next = [{ preview }, { board_id: 'b1', preview, settings_applied: [], settings_refused: ['x: skipped'] }];
  await pick('{"format":"carnivore-board"}');
  expect(calls.list).toHaveLength(1);
  document.querySelector<HTMLButtonElement>('[data-board-import-confirm]')!.click();
  for (let i = 0; i < 5; i++) await tick();
  expect(calls.list).toHaveLength(2);
  expect(body(calls.list[1]!).dry_run).toBeUndefined();
  expect(document.querySelector('[data-board-import-problem]')!.textContent).toContain('x: skipped');
});

test('the page explains itself in its band: title, one sentence, search, and the one primary', () => {
  const page = document.querySelector('.oc-page')!;
  const titlebar = page.querySelector('.oc-titlebar')!;
  expect(titlebar.querySelector('.oc-titlebar__title')!.textContent).toBe('dashboards');
  expect(titlebar.textContent).toContain('2 dashboards');
  const create = titlebar.querySelector<HTMLButtonElement>('[data-dashboard-new]')!;
  expect(create.getAttribute('data-btn')).toBe('confirm');
  const bar = page.querySelector('.oc-page__bar')!;
  expect(bar.querySelector('[data-page-lede]')!.textContent).toContain('your active dashboard is your home screen');
  expect(bar.querySelector('input[type="search"], input')).not.toBeNull();
  expect(bar.querySelector('[data-dashboard-duplicate]')).not.toBeNull();
  expect(bar.querySelector('[data-board-import]')).not.toBeNull();
  expect(page.querySelector('.oc-page__body [data-dashboards]')).not.toBeNull();
  expect(bar.querySelector('[data-dashboard]')).toBeNull();
});

test('the band and the data wear the two page grounds', () => {
  const rule = (selector: string): string => {
    const at = pageCss.indexOf(`${selector} {`);
    expect(at, selector).toBeGreaterThan(-1);
    return pageCss.slice(at, pageCss.indexOf('}', at));
  };
  expect(rule('.oc-titlebar')).toContain('background: var(--oc-ground-band)');
  expect(rule('.oc-page__bar')).toContain('background: var(--oc-ground-band)');
  expect(rule('.oc-page')).toContain('background: var(--oc-ground-content)');
  expect(tokensCss).toContain('--oc-ground-band: var(--oc-ground-chrome)');
  expect(tokensCss).toContain('--oc-ground-content: var(--oc-ground-page)');
});

test('each dashboard is a card with a preview of its grid; the home screen comes first and is marked', () => {
  const cards = [...document.querySelectorAll<HTMLElement>('[data-dashboard]')];
  expect(cards.map((card) => card.dataset['dashboard'])).toEqual(['home', 'b2']);
  expect(cards[0]!.classList.contains('dash-card--home')).toBe(true);
  expect(cards[0]!.querySelector('[data-dashboard-active]')!.textContent).toContain('home screen');
  expect(cards[1]!.querySelector('[data-dashboard-active]')).toBeNull();
  expect(row('b2').querySelector('[data-dashboard-preview]')!.getAttribute('data-dashboard-preview')).toBe('3');
  expect(row('b2').querySelectorAll('.dash-preview__box')).toHaveLength(3);
  expect(row('b2').textContent).toContain('3 widgets in 2 rows');
  expect(row('home').querySelector('[data-dashboard-edit]')!.textContent).toContain('edit layout');
  for (const action of ['activate', 'open', 'edit', 'delete', 'export']) {
    expect(row('b2').querySelector(`[data-dashboard-${action}]`), action).not.toBeNull();
  }
  expect(document.querySelector('[data-dashboard-new-tile]')).not.toBeNull();
});

test('edit opens a non-active dashboard in its own window with edit layout on', () => {
  const open = vi.spyOn(window, 'open').mockReturnValue(null);
  row('b2').querySelector<HTMLButtonElement>('[data-dashboard-edit]')!.click();
  expect(String(open.mock.calls[0]![0])).toBe('/static/popout.html?board=b2&edit=1&layout=1');
  expect(dashboardOpensEditing('?board=b2&edit=1&layout=1')).toBe(true);
  expect(dashboardOpensEditing('?board=b2&edit=1')).toBe(false);
  open.mockRestore();
});

test('the name renames in place: Enter sends it, Escape drops it', async () => {
  row('b2').querySelector<HTMLButtonElement>('[data-dashboard-rename]')!.click();
  flushSync();
  const input = row('b2').querySelector<HTMLInputElement>('[data-dashboard-name-input]')!;
  input.value = 'wallboard';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  calls.next = [{ dashboards: [], active: 'home', revision: 4, synced: true }];
  input.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
  await settle();
  expect(calls.list[0]!.path).toBe('/dashboards/b2');
  expect(calls.list[0]!.init?.method).toBe('PATCH');
  expect(body(calls.list[0]!).name).toBe('wallboard');
});

test('the search narrows the cards by name', () => {
  const field = document.querySelector<HTMLInputElement>('.oc-page__bar input')!;
  field.value = 'wal';
  field.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  expect([...document.querySelectorAll<HTMLElement>('[data-dashboard]')].map((card) => card.dataset['dashboard'])).toEqual(['b2']);
});

test('the preview shape: rows stack by height, slots share a row by fr', () => {
  const shape = boardShape(homeBoards.layouts['b2']);
  expect(shape.rows).toBe(2);
  const [projects, notes, closed] = shape.boxes;
  expect(projects!.width).toBeCloseTo(66.667, 2);
  expect(notes!.left).toBeCloseTo(66.667, 2);
  expect(closed!.top).toBeCloseTo(projects!.height, 5);
  expect(projects!.height + closed!.height).toBeCloseTo(100, 5);
  expect(boardShape(undefined)).toEqual({ boxes: [], rows: 0, widgets: 0 });
});
