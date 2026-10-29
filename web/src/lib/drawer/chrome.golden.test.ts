/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterAll, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

const calls: string[] = [];
const fakeLedger = vi.hoisted(() => ({ status: 'ok' as 'ok', data: null as unknown, fetchedAt: Date.now() as number | null, error: null as string | null }));
vi.mock('../../opscenter/api', () => ({ ledger: fakeLedger, primarySessionId: () => '' }));
vi.mock('../../opscenter/api/auth.svelte', () => ({
  auth: { state: 'signed-in' },
  initAuth: async () => {},
  ApiError: class ApiError extends Error {},
  authFetch: async (p: string) => {
    if (p === '/pack/machines') return { machines: [] };
    calls.push(p);
    return { v: 1, rev: 1, window: '1h', bucket_seconds: 60, start: 1_791_691_500, now: 1_791_695_055, state: 'ok', in: [100, null, 0], out: [10, null, 0], totals: null, rate: { span_seconds: 280, fresh: 2, cache_write: 3, cache_read: 5, out: 2 }, sources: [{ host_key: 'local', label: 'this computer', state: 'ok' }] };
  },
}));

import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import DrawerStats from '../drawer-tabs/DrawerStats.svelte';
import DrawerLedger from '../ledger-drawer/DrawerLedger.svelte';
import * as Bar from './bar';
import { mountDrawerHeader } from './header-mount';
import { publishFloorRows } from './floor-feed.svelte';
import { setCountFilter } from './count-filter.svelte';
import { accountChip } from '../drawer-hud/account-menu.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');
const REPO = path.resolve(process.cwd(), '..');
const GOLDEN = path.join(__dirname, '__goldens__', 'chrome-dom.json');
const recorded: Record<string, string> = fs.existsSync(GOLDEN) ? JSON.parse(fs.readFileSync(GOLDEN, 'utf8')) : {};
const taken: Record<string, string> = {};
const w = window as unknown as Record<string, unknown>;
const messages = enCatalog as Record<string, string>;

function canonical(root: Element): string {
  const KEEP = /^(role|aria-.*|data-.*|type|href|for|name|placeholder|disabled|checked|selected|hidden|open|value|title|tabindex|id|alt|src|target|rel)$/;
  const lines: string[] = [];
  const walk = (el: Element, depth: number): void => {
    const cls = [...el.classList].filter((c) => !/^svelte-/.test(c)).sort().join(' ');
    const attrs = [...el.attributes]
      .filter((a) => KEEP.test(a.name))
      .map((a) => `${a.name}=${a.value.replace(/\b(s?\d*-?[a-z]*-?_?[a-z0-9]{6,}-\d+|bits-\w+|\w+-\d+-\d+)\b/g, '#')}`)
      .sort();
    const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => (n.textContent ?? '').replace(/\s+/g, ' ').trim()).filter(Boolean).join(' | ').replace(/\d+s ago/g, 'Ns ago').replace(/reset in [\dhdms ]+/g, 'reset in T');
    lines.push(`${'  '.repeat(depth)}<${el.tagName.toLowerCase()}${cls ? ` .${cls.replace(/ /g, '.')}` : ''}${attrs.length ? ` [${attrs.join(' ')}]` : ''}>${own ? ` ${own}` : ''}`);
    for (const child of el.children) walk(child, depth + 1);
  };
  for (const child of root.children) walk(child, 0);
  return lines.join('\n');
}

const settle = async (): Promise<void> => {
  for (let i = 0; i < 40; i++) {
    await tick();
    flushSync();
    await new Promise((r) => setTimeout(r, 5));
  }
};

async function snap(name: string, el: Element): Promise<void> {
  await settle();
  taken[name] = canonical(el);
  if (!process.env.UPDATE_GOLDENS) expect(taken[name], `golden ${name}`).toBe(recorded[name]);
}

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(async () => {
  for (const m of mounted.splice(0)) await unmount(m);
  document.body.innerHTML = '';
  localStorage.clear();
  setCountFilter(null);
  Bar.reset();
  w.CloudeI18n = { t: (key: string) => messages[key] ?? key };
  w.VersionFooter = {
    RELEASE_NOTES_URL: 'https://example.test/releases',
    UNKNOWN_TEXT: 'version unknown',
    PREVIEW_TEXT: 'preview',
    readVersionText: () => '1.2.3',
    shortVersion: (full: string) => ({ text: `v${full}`, preview: false }),
  };
  accountChip.identity = null;
  delete w.CloudeWeb;
});
afterAll(() => {
  if (process.env.UPDATE_GOLDENS) {
    fs.mkdirSync(path.dirname(GOLDEN), { recursive: true });
    fs.writeFileSync(GOLDEN, `${JSON.stringify(taken, null, 1)}\n`);
  }
});

function drawerPage(): HTMLElement {
  const source = fs.readFileSync(path.join(REPO, 'client', 'index.html'), 'utf8');
  const start = source.indexOf('<aside id="session-sidebar-panel"');
  const end = source.indexOf('</aside>', start);
  document.body.innerHTML = source.slice(start, end + '</aside>'.length);
  return document.getElementById('session-sidebar-panel')!;
}

function headerOf(aside: HTMLElement): Element {
  const wrap = document.createElement('div');
  wrap.append(aside.querySelector('.session-sidebar-header')!.cloneNode(true));
  return wrap;
}

describe('the title bar', () => {
  test('brand, the two slots the widgets mount into, and the collapse control', async () => {
    const aside = drawerPage();
    mountDrawerHeader();
    await snap('header', headerOf(aside));
  });
});

describe('the stats row', () => {
  const rows = [
    { name: 'a', status: 'working' }, { name: 'b', status: 'idle', unread: true }, { name: 'c', status: 'dead' },
    { name: 'e', status: 'working_subagent', unread: true },
  ];
  test('counts, rate and chart', async () => {
    publishFloorRows(rows as never);
    document.body.innerHTML = '<div id="host"></div>';
    mounted.push(mount(DrawerStats, { target: document.getElementById('host')! }));
    await snap('stats', document.getElementById('host')!);
  });
});

describe('the providers panel', () => {
  const win = (kind: string, label: string, used_pct: number) => ({ kind, label, used_pct, resets_at: new Date(1_800_000_000_000).toISOString(), window_seconds: null });
  const account = (id: string, name: string, over: Record<string, unknown> = {}) => ({
    id, name, short_name: name, provider: 'claude', plan: 'max', identity: null, credential_state: 'ok', fetched_at: null, next_poll_at: null,
    error: null, color: null, managed: true, windows: [win('five_hour', '5h', 20), win('seven_day', '7d', 41)], ...over,
  });
  const SNAPSHOT = {
    accounts: [account('a', 'alpha'), account('b', 'bravo', { windows: [win('five_hour', '5h', 90), win('seven_day', '7d', 80)] }), account('c', 'charlie', { provider: 'codex', plan: 'plus', credential_state: 'expired' })],
    total: { accounts: 3, windows: [{ kind: 'five_hour', label: '5h', used_pct: 4, resets_at: null, accounts: 3 }, { kind: 'seven_day', label: '7d', used_pct: 48, resets_at: null, accounts: 3 }] },
    loop: { alive: true, last_pass_at: null },
  };
  const render = (): HTMLElement => {
    fakeLedger.data = SNAPSHOT;
    document.body.innerHTML = '<div id="host"></div>';
    const host = document.getElementById('host')!;
    mounted.push(mount(DrawerLedger, { target: host }));
    return host;
  };
  test('compact, expanded, glance, total only', async () => {
    const host = render();
    await snap('providers-compact', host);
    for (const name of ['providers-expanded', 'providers-glance', 'providers-total']) {
      host.querySelector<HTMLElement>('[data-ldp-toggle]')!.click();
      await snap(name, host);
    }
  });
});

describe('the bottom bar', () => {
  const paint = async (name: string): Promise<void> => {
    document.body.innerHTML = '<div id="session-sidebar-bar-slot"></div>';
    Bar.paint();
    await snap(name, document.getElementById('session-sidebar-bar-slot')!);
  };
  test('signed out', async () => {
    accountChip.identity = { kind: 'lurker', name: '', provider: null };
    await paint('bar-signed-out');
  });
  test('signed in, master all on', async () => {
    accountChip.identity = { kind: 'member', name: 'joe', provider: 'github' };
    w.CloudeWeb = { masterAllEnabled: () => true, setMasterAll: () => {} };
    await paint('bar-signed-in-crown');
  });
});
