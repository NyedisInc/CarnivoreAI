/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: string[] = [];
let packSize: number | null = null;
let answer: (path: string) => unknown = () => null;
vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {
    status: number;
    constructor(message: string, status = 0) {
      super(message);
      this.status = status;
    }
  },
  authFetch: async (p: string) => {
    if (p === '/pack/machines') return { machines: Array.from({ length: packSize ?? 0 }, (_, n) => ({ install_id: `m${n}` })) };
    calls.push(p);
    return answer(p);
  },
}));

import DrawerStats from './DrawerStats.svelte';
import { applyDrawerTab, DRAWER_STATS_ID, DRAWER_STATS_RATE_KEY, DRAWER_STATS_WINDOW_KEY } from './drawer-tabs';
import { BUILTIN_TABS } from '../dynamic-tabs/builtin';
import { publishFloorRows } from '../drawer/floor-feed.svelte';
import { activeCountFilter, setCountFilter } from '../drawer/count-filter.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import { statsFeed } from '../stats-feed/store.svelte';
import { setLocale } from '../i18n/index.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { chartBars, mergeBars } from '../stats-feed/rate';
import type { FeedBody } from '../stats-feed/types';
import { tooltipTargetFor } from '../tooltip/tooltip';

setLocale('en');
const REPO = path.resolve(process.cwd(), '..');

/** The drawer's <aside>, exactly as shipped. */
function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  const end = source.indexOf('</aside>', start);
  if (start < 0 || end < 0) throw new Error('the drawer markup is missing from client/index.html');
  return source.slice(start, end + '</aside>'.length);
}

function body(window: string, state = 'ok'): unknown {
  const off = state === 'stats_off';
  return {
    v: 1, rev: 1, window, bucket_seconds: 60, start: 1_791_691_500, now: 1_791_695_055, state,
    in: off ? [null, null, null] : [100, null, 0], out: off ? [null, null, null] : [10, null, 0],
    totals: null,
    rate: off ? null : { span_seconds: 280, fresh: 2, cache_write: 3, cache_read: 5, out: 2 },
    sources: [{ host_key: 'local', label: 'this computer', state: off ? 'stats_off' : 'ok' }],
  };
}

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => {
  document.body.innerHTML = drawerMarkup();
  localStorage.clear();
  calls.length = 0;
  packSize = null;
  setCountFilter(null);
  answer = (p) => body(new URL(p, 'http://x').searchParams.get('window') ?? '1h');
  publishFloorRows([
    { name: 'a', status: 'working' }, { name: 'b', status: 'idle', unread: true }, { name: 'c', status: 'dead' },
    { name: 'd', status: 'asleep', asleep: true }, { name: 'e', status: 'working_subagent', unread: true },
  ]);
});
afterEach(async () => {
  for (const m of mounted.splice(0)) await unmount(m);
  document.body.replaceChildren();
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

/** Let pending microtasks and timers settle, up to ~2 s, until `done` holds. */
async function settle(done: () => boolean = () => true): Promise<void> {
  for (let i = 0; i < 200; i += 1) {
    await tick();
    flushSync();
    if (done()) return;
    await new Promise((r) => setTimeout(r, 10));
  }
}

async function render(): Promise<HTMLElement> {
  const target = document.getElementById(DRAWER_STATS_ID);
  if (!target) throw new Error(`no #${DRAWER_STATS_ID} in the drawer markup`);
  mounted.push(mount(DrawerStats, { target }));
  await settle(() => target.querySelector('.dst-rate, .dst-word') !== null && !target.querySelector('.dst-word')?.textContent?.includes('reading'));
  return target;
}

const text = (el: Element | null): string => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();
const rateText = (bar: Element): string => {
  const copy = bar.querySelector('.dst-rate')?.cloneNode(true) as Element | undefined;
  copy?.querySelector('.dst-unit-short')?.remove();
  return text(copy ?? null);
};

test('counts come from the pushed rows and the rate reads up = out, down = in, per min', async () => {
  const bar = await render();
  expect(text(bar.querySelector('[data-kind="active"]'))).toBe('3');
  expect(text(bar.querySelector('[data-kind="working"]'))).toBe('2');
  expect(text(bar.querySelector('[data-kind="unread"]'))).toBe('2');
  expect(rateText(bar)).toBe('120 / 600 per min');
  expect(calls).toEqual(['/stats/feed?window=1h']);
});

test('clicking the rate walks sec > min > hour > day with no request; clicking the chart walks the windows with one GET each', async () => {
  const bar = await render();
  const rate = (): string => rateText(bar);
  const click = (sel: string): void => { bar.querySelector<HTMLButtonElement>(sel)!.click(); flushSync(); };
  click('.dst-rate');
  expect(rate()).toBe('7.2k / 36k per hour');
  click('.dst-rate');
  expect(rate()).toBe('172.8k / 864k per day');
  click('.dst-rate');
  expect(rate()).toBe('2 / 10 per sec');
  expect(calls).toEqual(['/stats/feed?window=1h']);
  expect(localStorage.getItem(DRAWER_STATS_RATE_KEY)).toBe('sec');

  expect(text(bar.querySelector('.dst-win'))).toBe('1h');
  click('.dst-chart');
  await settle(() => calls.length > 1);
  expect(text(bar.querySelector('.dst-win'))).toBe('5h');

  expect(calls).toEqual(['/stats/feed?window=1h', '/stats/feed?window=5h']);
  expect(localStorage.getItem(DRAWER_STATS_WINDOW_KEY)).toBe('5h');
  expect(statsFeed('1h')).toBeNull();
  click('.dst-win');
  expect(text(bar.querySelector('.dst-win'))).toBe('1d');
});

test('a gap bar is hatched, a measured zero is a stub, never the same', async () => {
  const bar = await render();
  expect(bar.querySelectorAll('.dst-bar').length).toBe(3);
  expect(bar.querySelectorAll('.dst-bar--gap').length).toBe(1);
  expect(bar.querySelectorAll('.dst-bar--zero').length).toBe(1);
});

test('stats off shows the named state in place of the token half and keeps the counts', async () => {
  answer = (p) => body(new URL(p, 'http://x').searchParams.get('window') ?? '1h', 'stats_off');
  const bar = await render();
  expect(text(bar.querySelector('.dst-word'))).toBe('stats off');
  expect(bar.querySelector('.dst-rate')).toBeNull();
  expect(text(bar.querySelector('[data-kind="active"]'))).toBe('3');
});

test('the menu tab hides the bar', async () => {
  const bar = await render();
  applyDrawerTab('menu', BUILTIN_TABS);
  expect(bar.hidden).toBe(true);
  applyDrawerTab('agents', BUILTIN_TABS);
  expect(bar.hidden).toBe(false);
});

test('the feed is released 5 s after the bar leaves the screen and held again on return', async () => {
  let notify: (entries: { isIntersecting: boolean }[]) => void = () => {};
  vi.stubGlobal('VisibilityObserver', class {
    constructor(cb: (e: { isIntersecting: boolean }[]) => void) { notify = cb; }
    observe(): void {}
    disconnect(): void {}
  });
  const bar = await render();
  expect(bar).toBeTruthy();
  expect(statsFeed('1h')).toBeNull();
  notify([{ isIntersecting: true }]);
  await settle();
  expect(statsFeed('1h')).not.toBeNull();
  vi.useFakeTimers();
  notify([{ isIntersecting: false }]);
  vi.advanceTimersByTime(4000);
  flushSync();
  expect(statsFeed('1h')).not.toBeNull();
  vi.advanceTimersByTime(1500);
  flushSync();
  expect(statsFeed('1h')).toBeNull();
});

function realWindow(): FeedBody {
  const inn: (number | null)[] = [];
  const out: (number | null)[] = [];
  for (let i = 0; i < 60; i += 1) {
    const gap = i >= 4 && i < 8;
    inn.push(gap ? null : 5_900_000 + ((i * 7919) % 600_000));
    out.push(gap ? null : 39_000 + ((i * 104729) % 8_000));
  }
  return {
    ...(body('1h') as FeedBody), bucket_seconds: 60, start: 1_791_691_500, in: inn, out,
    rate: { span_seconds: 280, fresh: 2, cache_write: 3, cache_read: 5, out: 2 },
  };
}

test('60 buckets fold into bars at least 2px wide with a 1px gap, and nothing is lost', async () => {
  const fixture = realWindow();
  const merged = mergeBars(chartBars(fixture), 16, fixture.bucket_seconds);
  expect(merged.length).toBeLessThanOrEqual(16);
  const total = chartBars(fixture).reduce((a, b) => a + (b.total ?? 0), 0);
  expect(merged.reduce((a, b) => a + (b.total ?? 0), 0)).toBe(total);
  expect(merged[merged.length - 1]!.end).toBe(fixture.start + 60 * 60);
  expect(merged.every((b) => b.count === 4)).toBe(true);
  expect(merged[1]!.total).toBeNull();
  expect(merged[0]!.total).not.toBeNull();

  answer = () => fixture;
  const bar = await render();
  const drawn = [...bar.querySelectorAll<HTMLElement>('.dst-bar')];
  expect(drawn.length).toBe(merged.length);
  expect(drawn.length).toBeLessThanOrEqual(16);
  const css = fs.readFileSync(path.join(REPO, 'web/src/lib/drawer-tabs/DrawerStats.svelte'), 'utf8');
  expect(css).toMatch(/\.dst-bar \{[^}]*flex: 0 0 2px;[^}]*width: 2px;/);
  expect(css).toMatch(/\.dst-bars \{[^}]*gap: calc\(var\(--oc-space-1\) \/ 4\);/);
  expect(drawn.every((el) => !el.hasAttribute('title'))).toBe(true);
  expect(drawn[1]!.classList.contains('dst-bar--gap')).toBe(true);
});

test('a paired computer that cannot be reached hatches the chart from its last good time, never zeros', async () => {
  const fixture = realWindow();
  const through = fixture.start + 40 * 60;
  answer = () => ({
    ...fixture, state: 'partial',
    sources: [
      { host_key: 'local', label: 'this computer', state: 'ok' },
      { host_key: 'peer-1', label: 'studio', state: 'unreachable', reason: 'timeout', data_through: through },
    ],
  });
  const bar = await render();
  const band = bar.querySelector<HTMLElement>('.dst-band');
  expect(band).not.toBeNull();
  expect(band!.dataset.cue).toBe('down');
  expect(band!.style.left).toBe('30px');
  expect(bar.querySelector('.dst-flag')?.getAttribute('data-cue')).toBe('down');
  expect(bar.querySelector('.dst-row')?.getAttribute('data-state') ?? bar.querySelector('[data-state]')?.getAttribute('data-state')).toBe('partial');

  answer = () => ({ ...fixture, state: 'partial', sources: [{ host_key: 'peer-1', label: 'studio', state: 'paused', data_through: through }] });
  await unmount(mounted.pop()!);
  const again = await render();
  expect(again.querySelector<HTMLElement>('.dst-band')?.dataset.cue).toBe('partial');
  answer = () => body('1h');
  await unmount(mounted.pop()!);
  const clean = await render();
  expect(clean.querySelector('.dst-band')).toBeNull();
});

test.each([
  ['401', 401, 'sign in for stats'],
  ['404', 404, 'stats not on this install'],
  ['501', 501, 'stats not on this install'],
  ['a network failure', 0, 'stats not readable'],
])('a failed read (%s) names itself and never leaves "reading stats" up', async (_label, status, words) => {
  answer = () => { throw new ApiError('nope', status); };
  const bar = await render();
  await settle(() => !text(bar.querySelector('.dst-word')).includes('reading'));
  expect(text(bar.querySelector('.dst-word'))).toBe(words);
  expect(bar.querySelector('.dst-rate')).toBeNull();
  expect(text(bar.querySelector('[data-kind="active"]'))).toBe('3');
});

test('a newly chosen window keeps the last body, dimmed, until its first read lands', async () => {
  const bar = await render();
  let land: (v: unknown) => void = () => {};
  answer = (p) => new Promise((resolve) => { land = () => resolve(body(new URL(p, 'http://x').searchParams.get('window') ?? '5h')); });
  bar.querySelector<HTMLButtonElement>('.dst-chart')!.click();
  await settle(() => bar.querySelector('.dst-row')?.getAttribute('data-held') === 'true');
  expect(bar.querySelector('.dst-row')?.getAttribute('data-held')).toBe('true');
  expect(bar.querySelector('.dst-tokens')?.classList.contains('dst-dim')).toBe(true);
  expect(bar.querySelector('.dst-rate')).not.toBeNull();
  land(null);
  await settle(() => bar.querySelector('.dst-row')?.getAttribute('data-held') !== 'true');
  expect(bar.querySelector('.dst-tokens')?.classList.contains('dst-dim')).toBe(false);
});

test('once the bar is released the held body is dropped, not shown dimmed until the next read', async () => {
  let notify: (entries: { isIntersecting: boolean }[]) => void = () => {};
  vi.stubGlobal('VisibilityObserver', class {
    constructor(cb: (e: { isIntersecting: boolean }[]) => void) { notify = cb; }
    observe(): void {}
    disconnect(): void {}
  });
  const bar = await render();
  notify([{ isIntersecting: true }]);
  await settle(() => bar.querySelector('.dst-rate') !== null);
  expect(bar.querySelector('.dst-rate')).not.toBeNull();
  vi.useFakeTimers();
  notify([{ isIntersecting: false }]);
  vi.advanceTimersByTime(5500);
  flushSync();
  vi.useRealTimers();
  expect(statsFeed('1h')).toBeNull();
  expect(bar.querySelector('.dst-rate')).toBeNull();
  expect(text(bar.querySelector('.dst-word'))).toBe('reading stats');
  calls.length = 0;
  notify([{ isIntersecting: true }]);
  await settle(() => bar.querySelector('.dst-rate') !== null);
  expect(calls).toEqual(['/stats/feed?window=1h']);
  expect(bar.querySelector('.dst-tokens')?.classList.contains('dst-dim')).toBe(false);
});

test('a failed read after a good one names itself instead of showing stale numbers, and the next good read restores them', async () => {
  const bar = await render();
  expect(bar.querySelector('.dst-rate')).not.toBeNull();
  answer = () => { throw new ApiError('nope', 500); };
  await statsFeed('1h')!.refresh(true);
  await settle(() => bar.querySelector('.dst-word') !== null);
  expect(text(bar.querySelector('.dst-word'))).toBe('stats not readable');
  expect(bar.querySelector('.dst-rate')).toBeNull();
  answer = () => body('1h');
  await statsFeed('1h')!.refresh(true);
  await settle(() => bar.querySelector('.dst-rate') !== null);
  expect(bar.querySelector('.dst-word')).toBeNull();
  expect(bar.querySelector('.dst-tokens')?.classList.contains('dst-dim')).toBe(false);
});

function stubWidths(tokens: number, readout: number): void {
  vi.stubGlobal('ResizeObserver', class { observe(): void {} disconnect(): void {} });
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get(this: HTMLElement) { return this.classList.contains('dst-tokens') ? tokens : 0; } });
  Object.defineProperty(HTMLElement.prototype, 'offsetWidth', { configurable: true, get(this: HTMLElement) { return this.classList.contains('dst-rate') ? readout : 0; } });
}
afterEach(() => {
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
  delete (HTMLElement.prototype as unknown as Record<string, unknown>).offsetWidth;
});

test('the chart is left out when the readout leaves less than four bars of room, and the figures stay', async () => {
  stubWidths(113, 126);
  const bar = await render();
  expect(bar.querySelector('.dst-chart')).toBeNull();
  expect(bar.querySelector('.dst-rate')).not.toBeNull();
});

test('the chart takes only the bars that fit beside the readout, up to sixteen', async () => {
  answer = () => realWindow();
  stubWidths(183, 126);
  let bar = await render();
  expect(bar.querySelectorAll('.dst-bar').length).toBeLessThanOrEqual(9);
  expect(bar.querySelectorAll('.dst-bar').length).toBeGreaterThanOrEqual(4);
  await unmount(mounted.pop()!);
  stubWidths(400, 126);
  bar = await render();
  expect(bar.querySelectorAll('.dst-bar').length).toBeGreaterThan(9);
});

test('the token figures keep their capital K, M, B, T under the lowercase button rule (#1592)', () => {
  const css = fs.readFileSync(path.join(REPO, 'web/src/lib/drawer-tabs/DrawerStats.svelte'), 'utf8');
  expect(css).toMatch(/\.dst-act \{[^}]*text-transform: lowercase;/);
  expect(css).toMatch(/\.dst-figure \{[^}]*text-transform: none;/);
});

test('a click on a count filters the list to it with a yellow-border state, and a second click clears it', async () => {
  const bar = await render();
  const working = bar.querySelector<HTMLButtonElement>('[data-kind="working"]')!;
  expect(working.getAttribute('aria-pressed')).toBe('false');
  working.click();
  flushSync();
  expect(activeCountFilter()).toBe('working');
  expect(working.dataset.filter).toBe('on');
  expect(working.getAttribute('aria-pressed')).toBe('true');
  bar.querySelector<HTMLButtonElement>('[data-kind="unread"]')!.click();
  flushSync();
  expect(activeCountFilter()).toBe('unread');
  expect(working.dataset.filter).toBeUndefined();
  bar.querySelector<HTMLButtonElement>('[data-kind="unread"]')!.click();
  flushSync();
  expect(activeCountFilter()).toBeNull();
});

test('the strip has no box, the token readout sits right with one decimal, and the wolf count shows only at 2+ computers', async () => {
  const css = fs.readFileSync(path.join(process.cwd(), 'src/lib/drawer-tabs/DrawerStats.svelte'), 'utf8');
  const rule = (sel: string): string => css.slice(css.indexOf(`${sel} {`), css.indexOf('}', css.indexOf(`${sel} {`)));
  expect(rule('.dst-field'), 'no border around the strip').not.toMatch(/^\s*(border|background)[\w-]*:/m);
  expect(rule('.dst-tokens'), 'token readout pushed to the right').toMatch(/justify-content: flex-end/);
  const run = async (size: number | null): Promise<HTMLElement> => {
    await Promise.all(mounted.splice(0).map((m) => unmount(m)));
    packSize = size;
    await packMachines.refresh(true);
    answer = (p) => ({ ...(body(new URL(p, 'http://x').searchParams.get('window') ?? '1h') as object), rate: { span_seconds: 280, fresh: 0, cache_write: 0, cache_read: 58_800 / 60, out: 4_490_000 / 60 } });
    return render();
  };
  let bar = await run(3);
  await settle(() => bar.querySelector('.dst-pack') !== null);
  const kids = [...bar.querySelector('.dst-field')!.children].map((c) => c.classList[0]);
  expect(kids, 'counts first, tokens after, nothing trailing the field').toEqual(['dst-counts', 'dst-tokens']);
  expect([...bar.querySelector('.dst-row')!.children].map((c) => c.classList[0]), 'no spacer after the field').toEqual(['dst-field']);
  expect(text(bar.querySelector('.dst-pack'))).toBe('3');
  expect(bar.querySelector('.dst-pack svg'), 'the wolf glyph').not.toBeNull();
  expect(bar.querySelector('.dst-pack')!.getAttribute('aria-label')).toBe('3 computers in the pack');
  expect(rateText(bar)).toBe('4.5M / 58.8k per min');
  for (const size of [1, 0, null]) {
    bar = await run(size);
    await settle();
    expect(bar.querySelector('.dst-pack'), `no wolf at ${size}`).toBeNull();
  }
});

test('the stats bar shows no tooltip, leads with the wolf and has no automations figure (#1687)', async () => {
  answer = () => realWindow();
  packSize = 3;
  await packMachines.refresh(true);
  const bar = await render();
  await settle(() => bar.querySelector('.dst-pack') !== null);
  expect(bar.querySelectorAll('[data-kind="active"], [data-kind="working"], [data-kind="unread"]').length).toBe(3);
  for (const sel of ['.dst-pack', '.dst-rate', '.dst-chart']) expect(bar.querySelector(sel), sel).not.toBeNull();
  expect(bar.querySelectorAll('.dst-bar').length).toBeGreaterThanOrEqual(4);
  const row = bar.querySelector('.dst-row')!;
  const all = [row, ...row.querySelectorAll('*')];
  expect(all.length).toBeGreaterThan(20);
  for (const el of all) expect(tooltipTargetFor(el), el.className.toString()).toBeNull();
  expect(all.filter((el) => el.hasAttribute('title') && !el.classList.contains('status-led')), 'titles the bar owns').toEqual([]);
  expect(bar.querySelector('.dst-counts')!.firstElementChild!.classList.contains('dst-pack')).toBe(true);
  expect(bar.querySelector('[data-kind="automations"]')).toBeNull();
  expect(bar.querySelector('.dst-spacer')).toBeNull();
  for (const b of bar.querySelectorAll('.dst-count')) expect((b.getAttribute('aria-label') ?? '').length, 'count button names itself').toBeGreaterThan(0);
});
