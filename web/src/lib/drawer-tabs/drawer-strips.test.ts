/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const PACK = 3;
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
    if (p === '/pack/machines') return { machines: Array.from({ length: 3 }, (_, n) => ({ install_id: `m${n}` })) };
    return feed();
  },
}));

import DrawerSearch from './DrawerSearch.svelte';
import DrawerStats from './DrawerStats.svelte';
import { DRAWER_SEARCH_ID, DRAWER_STATS_ID } from './drawer-tabs';
import * as Search from '../drawer/search';
import { publishFloorRows } from '../drawer/floor-feed.svelte';
import { setCountFilter } from '../drawer/count-filter.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import { setLocale } from '../i18n/index.svelte';
import { canonicalDom } from '../sidebar-shell/legacy-fixture';

setLocale('en');
const REPO = path.resolve(process.cwd(), '..');

function feed(): unknown {
  const inn: (number | null)[] = [];
  const out: (number | null)[] = [];
  for (let i = 0; i < 60; i += 1) {
    const gap = i >= 4 && i < 8;
    inn.push(gap ? null : 5_900_000 + ((i * 7919) % 600_000));
    out.push(gap ? null : 39_000 + ((i * 104729) % 8_000));
  }
  return {
    v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1_791_691_500, now: 1_791_695_055, state: 'ok', in: inn, out,
    totals: null, rate: { span_seconds: 280, fresh: 2, cache_write: 3, cache_read: 5, out: 2 },
    sources: [{ host_key: 'local', label: 'this computer', state: 'ok' }],
  };
}

/** The drawer's <aside>, exactly as shipped. */
function drawerMarkup(): string {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  const end = source.indexOf('</aside>', start);
  return source.slice(start, end + '</aside>'.length);
}

const mounted: ReturnType<typeof mount>[] = [];
const win = globalThis as unknown as Record<string, unknown>;
beforeEach(() => {
  document.body.innerHTML = drawerMarkup();
  localStorage.clear();
  vi.spyOn(console, 'log').mockImplementation(() => {});
  Search.setQuery('');
  win.SessionSidebarSearch = {
    getQuery: Search.getQuery, setQuery: Search.setQuery, matchesRow: Search.matchesRow,
    matchesLabel: Search.matchesLabel, noMatchesHtml: Search.noMatchesHtml, normalize: Search.normalize,
  };
  publishFloorRows([
    { name: 'a', status: 'working' }, { name: 'b', status: 'idle', unread: true }, { name: 'c', status: 'dead' },
    { name: 'e', status: 'working_subagent', unread: true },
  ]);
  setCountFilter(null);
});
afterEach(async () => {
  for (const m of mounted.splice(0)) await unmount(m);
  document.body.replaceChildren();
  delete win.SessionSidebarSearch;
  setCountFilter(null);
  vi.restoreAllMocks();
});

/** Let pending microtasks and timers settle, up to ~2 s, until `done` holds. */
async function settle(done: () => boolean): Promise<void> {
  for (let i = 0; i < 200; i += 1) {
    await tick();
    flushSync();
    if (done()) return;
    await new Promise((r) => setTimeout(r, 10));
  }
}

async function searchCases(): Promise<string> {
  const target = document.getElementById(DRAWER_SEARCH_ID)!;
  mounted.push(mount(DrawerSearch, { target }));
  flushSync();
  const empty = canonicalDom(target);
  const input = target.querySelector('input')!;
  input.value = 'api';
  input.dispatchEvent(new Event('input', { bubbles: true }));
  flushSync();
  return ['=== search, empty', empty, '=== search, with a query', canonicalDom(target)].join('\n');
}

async function statsCase(): Promise<string> {
  await packMachines.refresh(true);
  setCountFilter('working');
  const target = document.getElementById(DRAWER_STATS_ID)!;
  mounted.push(mount(DrawerStats, { target }));
  await settle(() => target.querySelector('.dst-pack') !== null && target.querySelector('.dst-rate') !== null);
  return ['=== stats, pack, working filter, rate and chart', canonicalDom(target)].join('\n');
}

function undoWrapperSwaps(dom: string): string {
  return dom
    .replace(/<input [^>]*>/g, (tag) => tag.replace(' data-field=""', '').replace('class="', 'class="oc-field '))
    .replace(/class="oc-btn oc-btn--tool (ds-mode|dst-count)\b/g, 'class="$1')
    .replace(/<button [^>]*class="dst-(?:count|act)\b[^>]*>/g, (tag) => {
      const bare = tag.replace(' data-btn="quiet"', '');
      return bare.includes('dst-act') ? bare.replace('class="dst-act', 'class="oc-btn oc-btn--tool dst-act') : bare;
    });
}

test('the search row and the stats strip draw the recorded DOM', async () => {
  const search = await searchCases();
  const stats = await statsCase();
  expect(stats).toContain(`aria-label="${PACK} computers in the pack"`);
  const dom = undoWrapperSwaps(`${search}\n${stats}`.replace(/ svelte-[a-z0-9]+/g, ''));
  await expect(dom).toMatchFileSnapshot('./__goldens__/drawer-strips.html');
});

const STRIP_DIR = path.join(process.cwd(), 'src', 'lib', 'drawer-tabs');

const STRIP_KNOWN: Record<string, string> = {
  'CascadeMenu.svelte': 'menu rows',
  'DrawerMenu.svelte': 'menu flyout rows',
};

export function handMadeControls(source: string): string[] {
  const markup = source.replace(/<!--[\s\S]*?-->/g, '').replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '');
  const out: string[] = [];
  for (const m of markup.matchAll(/<(button|input)\b[^>]*>/g)) {
    const tag = m[0];
    if (m[1] === 'input' && (/\boc-field\b/.test(tag) || !/\bdata-field\b/.test(tag))) out.push('input');
    if (m[1] === 'button' && !/\boc-btn\b|\boc-ibtn\b|\bdata-btn\b/.test(tag)) out.push('button');
  }
  return out;
}

describe('strip control conformance (wrapper package S-5)', () => {
  const offenders = fs.readdirSync(STRIP_DIR)
    .filter((f) => f.endsWith('.svelte'))
    .filter((f) => handMadeControls(fs.readFileSync(path.join(STRIP_DIR, f), 'utf8')).length > 0);

  test('no drawer strip draws a hand-made input or button', () => {
    expect(offenders.filter((f) => !(f in STRIP_KNOWN))).toEqual([]);
  });
  test('every STRIP_KNOWN row still applies (the list only shrinks)', () => {
    expect(Object.keys(STRIP_KNOWN).filter((f) => !offenders.includes(f))).toEqual([]);
  });
  test('can go red: an .oc-field input and a bare button are seen, the shared ones are not', () => {
    expect(handMadeControls('<input type="text" class="oc-field ds-input" />')).toEqual(['input']);
    expect(handMadeControls('<button type="button" class="dst-count">1</button>')).toEqual(['button']);
    expect(handMadeControls('<input class="ds-input" data-field /><button class="oc-btn oc-btn--tool dst-count"></button>')).toEqual([]);
    expect(handMadeControls('<!-- <button class="x"> --><button class="oc-ibtn oc-ibtn--bare"></button>')).toEqual([]);
  });
});
