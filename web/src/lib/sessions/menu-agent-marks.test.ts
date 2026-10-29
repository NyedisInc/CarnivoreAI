/** @vitest-environment jsdom */
import fs from 'node:fs';
import path from 'node:path';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const listing = vi.hoisted(() => ({ data: [] as unknown[] }));
vi.mock('../../opscenter/api/sessions.svelte', () => ({ sessions: listing }));
vi.mock('../browser/api.svelte', () => ({ browsers: { data: [] } }));

import CascadeMenu from '../drawer-tabs/CascadeMenu.svelte';
import { buildTabMenu } from '../../opscenter/shell/tab-menu';
import { terminalLayout } from '../../opscenter/engine/layout.svelte';
import type { SessionInfo } from '../../opscenter/api/types';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';

// jsdom has neither method.
installPopoverPolyfill();

type Win = Record<string, unknown>;
const win = globalThis as unknown as Win;
const REPO = path.resolve(process.cwd(), '..');

/** One listing row, every signal on the WRAPPER, where the server puts it. */
function row(
  id: string,
  label: string,
  family: string | null,
  status: string,
  project: [number, string] | null,
  extra: Partial<SessionInfo> = {},
): SessionInfo {
  return {
    session: { id, working_dir: '/work/' + id },
    label,
    tmux_session: `cloude_${id}`,
    agent_family: family,
    activity_status: status,
    unread: false,
    startup_gate: null,
    status_source: 'registry',
    activity_hint: null,
    project_id: project ? project[0] : null,
    project_name: project ? project[1] : null,
    ...extra,
  } as unknown as SessionInfo;
}

const ROWS = [
  row('a', 'alpha', 'claude', 'working', [1, 'api']),
  row('b', 'bravo', 'codex', 'idle', [1, 'api'], { unread: true }),
  row('c', 'charlie shell', 'shell', 'idle', [2, 'ops']),
  row('d', 'delta', null, 'question', null),
];

const EXPECT: Record<string, { inner: string; family: string; led: RegExp; provider: string }> = {
  a: { inner: 'working', family: 'claude', led: /^working/, provider: 'claude' },
  b: { inner: 'disconnected', family: 'codex', led: /^idle/, provider: 'codex (openai)' },
  c: { inner: 'idle', family: 'shell', led: /^idle/, provider: 'shell' },
  d: { inner: 'waiting-permission', family: 'unknown', led: /^your turn/, provider: 'agent not determined' },
};

const mounted: ReturnType<typeof mount>[] = [];

beforeEach(() => {
  vi.spyOn(console, 'log').mockImplementation(() => {});
  new Function(fs.readFileSync(path.join(REPO, 'client', 'js', 'agent-family-icon.js'), 'utf8'))();
  win.SessionTransport = { stateFor: (name: string) => (name === 'cloude_b' ? 'disconnected' : 'connected') };
  win.TerminalController = { _sessionId: () => 's-page' };
  terminalLayout.bindSession('cloude_marks_test');
  listing.data = ROWS;
  document.body.innerHTML = '<button id="anchor">open</button><div id="host"></div>';
});

afterEach(async () => {
  for (const app of mounted.splice(0)) await unmount(app);
  terminalLayout.resetAll();
  terminalLayout.bindSession('');
  for (const name of ['AgentFamilyIcon', 'SessionTransport', 'TerminalController', 'API']) delete win[name];
  document.body.replaceChildren();
  vi.restoreAllMocks();
});

const anchor = (): HTMLElement => document.getElementById('anchor')!;
const host = (): HTMLElement => document.getElementById('host')!;
const node = (id: string): HTMLElement => document.querySelector<HTMLElement>(`[data-node="${id}"]`)!;

function click(el: HTMLElement): void {
  el.click();
  flushSync();
}

function accessibleName(el: Element): string {
  const own = el.getAttribute('aria-label');
  if (own !== null) return own;
  if (el.getAttribute('aria-hidden') === 'true') return '';
  return [...el.childNodes]
    .map((child) => (child.nodeType === 3 ? (child.textContent ?? '') : child.nodeType === 1 ? accessibleName(child as Element) : ''))
    .join(' ')
    .replace(/\s+/g, ' ')
    .trim();
}

function expectMarks(entry: HTMLElement, nameSel: string, id: string): void {
  const want = EXPECT[id]!;
  const led = entry.querySelector<HTMLElement>('.status-led');
  const mark = entry.querySelector<HTMLElement>('.agent-marks-provider');
  const name = entry.querySelector<HTMLElement>(nameSel);
  if (want.family === 'shell') {
    expect(led, `${id}: a shell entry has no status light`).toBeNull();
    expect(mark, `${id}: the entry has a provider mark`).not.toBeNull();
    expect(mark!.compareDocumentPosition(name!) & Node.DOCUMENT_POSITION_FOLLOWING, `${id}: mark before name`).toBeTruthy();
    expect(accessibleName(entry), `${id}: provider in the accessible name`).toContain(want.provider);
    return;
  }
  expect(led, `${id}: the entry has a status light`).not.toBeNull();
  expect(mark, `${id}: the entry has a provider mark`).not.toBeNull();
  expect(name, `${id}: the entry has its name`).not.toBeNull();
  expect(led!.compareDocumentPosition(mark!) & Node.DOCUMENT_POSITION_FOLLOWING, `${id}: light before mark`).toBeTruthy();
  expect(mark!.compareDocumentPosition(name!) & Node.DOCUMENT_POSITION_FOLLOWING, `${id}: mark before name`).toBeTruthy();
  expect(led!.dataset.inner, `${id}: the light is fed the row's own signals`).toBe(want.inner);
  expect(mark!.dataset.agentFamily, `${id}: the drawer's mark for the row's family`).toBe(want.family);
  expect(mark!.querySelector('svg'), `${id}: the mark is drawn`).not.toBeNull();
  const spoken = accessibleName(entry);
  expect(led!.getAttribute('aria-label') ?? '', `${id}: the status is spoken`).toMatch(want.led);
  expect(spoken, `${id}: status in the accessible name`).toContain(led!.getAttribute('aria-label'));
  expect(spoken, `${id}: provider in the accessible name`).toContain(want.provider);
}

test('the real drawer mark is loaded: the claude mark is the orange starburst', () => {
  const svg = (win.AgentFamilyIcon as { svg(f: string): string }).svg('claude');
  expect(svg).toContain('#d97757');
});

test('terminal "+" tab menu: every session under agent > project carries light and mark', () => {
  const root = buildTabMenu({
    rows: ROWS,
    name: (r) => r.label ?? r.session.id,
    open: () => {},
    wake: () => {},
    newAgent: () => {},
    newAgentInProject: () => {},
    newTerminal: () => {},
    openBlueprints: () => {},
    blueprints: [],
    launchBlueprint: () => {},
    openSessionIds: new Set(),
    layoutSessionIds: [],
    projects: [],
  });
  mounted.push(mount(CascadeMenu, { target: host(), props: { root, anchor: anchor(), label: 'new tab', onClose: () => {} } }));
  flushSync();
  click(node('agent'));
  expect(node('agent/new').querySelector('.agent-marks'), '"new agent" is not a session').toBeNull();
  expect(node('agent/p:1').querySelector('.agent-marks'), 'a project is not a session').toBeNull();
  click(node('agent/p:1'));
  expectMarks(node('agent/p:1/a'), '.acm-label', 'a');
  expectMarks(node('agent/p:1/b'), '.acm-label', 'b');
  click(node('agent/rogue'));
  expectMarks(node('agent/rogue/d'), '.acm-label', 'd');
});

test('a shell and a browser session carry no status light; an agent and an undetermined family do (#623)', async () => {
  const { showsStatusLight } = await import('./agent-marks');
  expect(showsStatusLight('shell')).toBe(false);
  expect(showsStatusLight('browser')).toBe(false);
  expect(showsStatusLight('claude')).toBe(true);
  expect(showsStatusLight(null)).toBe(true);
});
