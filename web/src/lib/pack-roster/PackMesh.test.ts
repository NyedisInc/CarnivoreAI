/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; init?: RequestInit }[] = [];
let view: Record<string, unknown>;
let machines: unknown[];
let hostRows: unknown[];
let machinesExtra: Record<string, unknown> = {};
const NONE = { computers: [], argent_known: true, not_tracked: [] };
let removed: unknown = NONE;
let grantRows: unknown[] = [];
let peerRows: unknown[] = [];

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    const method = init?.method ?? 'GET';
    if (path === '/computers' && method === 'GET') return structuredClone(view);
    if (path === '/pack/machines' && method === 'GET') return { machines: structuredClone(machines), settings: {}, tracks_master: false, ...machinesExtra };
    if (path === '/hosts' && method === 'GET') return { status: 'ok', hosts: structuredClone(hostRows) };
    if (path === '/pack/removed-logins') return structuredClone(removed);
    if (path === '/federation/peers') return structuredClone(peerRows);
    if (path === '/federation/pending-pairs') return [];
    if (path === '/federation/discovered') return { discovered: [], state: 'on' };
    if (path === '/federation/settings') return { advertise: true, state: 'on', pack_name: null };
    if (path === '/federation/grants') return structuredClone(grantRows);
    return {};
  },
}));
vi.mock('../modal', () => ({ openModal: vi.fn(async () => true) }));

import { auth } from '../../opscenter/api/auth.svelte';
import { computers } from '../computers/computers-store.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import MachineEditor from '../pack-machines/MachineEditor.svelte';
import { setLocale } from '../i18n/index.svelte';
import PackRoster from './PackRoster.svelte';
import { hosts, peers, discovered } from './roster-store.svelte';
import { openComputer, rosterUi } from './roster-ui.svelte';
import { openModal } from '../modal';

setLocale('en');
const NOW = Date.parse('2026-11-22T12:00:00Z');

const SELF = { install_id: 'me', label: 'studio', fid_short: 'ab12cd', role: 'member',
  link: { state: 'listening', port: 8443, join_open: false, addresses: [], code_paused_until: null },
  main: { label: 'alpha', state: 'connected', last_link_at: null, reachable_note: false } };
const RESERVE = { in_use: { cpu_pct: 50, mem_pct: 50 }, away: { cpu_pct: 80, mem_pct: 80 }, schedule: { in_use_from: '09:00', in_use_to: '17:00', days: [1, 2, 3] }, keyboard_rule: { enabled: false, idle_minutes: 5 } };
const SNAP = { load: { cores: 8, load_1: 1, memory_percent: 10, disk_percent: 10 }, battery: null, reserve: { level: 'in_use', cpu_pct: 50, mem_pct: 50, source: 'config', config: RESERVE },
  restrictions: { may_install_tools: true, may_receive_credentials: false, may_receive_global_setup: true, may_update_carnivore: true, may_host_agents: true, may_receive_projects: true, max_agents: null, allowed_projects: [], allowed_companies: [] } };
const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: id === 'me', is_master: id === 'alpha', paired: id === 'alpha',
  state: 'ok', capabilities: [], specs: null, snapshot: id === 'alpha' ? SNAP : null, age_seconds: 5, ...over });
const alphaEntry = { install_id: 'alpha', label: 'alpha', host_key: null, transport: 'tls', role: 'main', state: 'connected', direction: 'both', fid: 'alphafid000', fid_short: 'alphaf',
  joined_at: null, last_link_at: '2026-11-22T11:59:00Z', possible_duplicate_of: null };
const host = (key: string, over: Record<string, unknown> = {}) => ({ key, label: key, local: false, ssh_target: `alex@${key}`, ssh_port: null, socket: 'carnivore-remote', enabled: true,
  session_count: 0, probe_state: 'ok', probe_detail: null, probed_at: null, tmux_path: null, tmux_version: '3.4', login_path: null, agent_paths: null, login_shell: '/bin/zsh',
  machine_id: null, remote_carnivore: null, computer_install_id: null, created_at: '', updated_at: '', ...over });

const mounted: ReturnType<typeof mount>[] = [];
async function render(): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(PackRoster, { target, props: {} }));
  await Promise.all([computers.refresh(true), packMachines.refresh(true), hosts.refresh(true), peers.refresh(true), discovered.refresh(true)]);
  await settle();
  return target;
}
async function editor(id: string): Promise<HTMLElement> {
  const target = document.createElement('div');
  document.body.append(target);
  const m = packMachines.data!.machines.find((x) => x.install_id === id)!;
  mounted.push(mount(MachineEditor, { target, props: { machine: m } }));
  await settle();
  return target;
}
const norm = (html: string): string => html.replace(/<!---->/g, '').replace(/\s+/g, ' ').replace(/> </g, '><').replace(/rank-[a-z0-9]+-label/g, 'rank-ID-label');

/** Let promises settle and Svelte paint. */
async function settle(): Promise<void> {
  for (let i = 0; i < 5; i++) await new Promise((r) => setTimeout(r, 0));
  flushSync();
}
function member(on: boolean): void {
  view = { self: SELF, computers: [alphaEntry], invites: [], add_jobs: [] };
  machines = [machine('me', { capabilities: on ? ['pack.mesh_v1'] : [] }), machine('alpha'), machine('charlie', { state: 'reported_connected' }), machine('delta', { state: 'reported_connected' })];
  hostRows = [host('alpha', { computer_install_id: 'alpha' }), host('mesh-charlie', { ssh_target: '' })];
  machinesExtra = {};
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ['Date'] });
  vi.setSystemTime(NOW);
  auth.state = 'signed-in';
  calls.length = 0;
  removed = NONE;
  grantRows = [];
  peerRows = [];
  Object.assign(rosterUi, { filter: 'all', q: '', openId: null, tab: 'overview', mode: null, settings: true, landSsh: false, view: 'cards' });
});
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
  vi.useRealTimers();
});

describe('the Pack page with the mesh switch off', () => {
  test('renders as it did before the mesh and never reads the removed logins', async () => {
    member(false);
    const root = await render();
    openComputer('charlie', 'link');
    await settle();
    const ed = await editor('alpha');
    const html = [norm(root.innerHTML), norm(ed.innerHTML)].join('\n----\n');
    await expect(html).toMatchFileSnapshot('./__snapshots__/PackMesh.off.html');
    expect(calls.some((c) => c.path === '/pack/removed-logins')).toBe(false);
  });
});

const link = (id: string, state: string, over: Record<string, unknown> = {}) => ({ install_id: id, state, since: NOW / 1000 - 300, dialed_by: 'this', standing: true, on_demand: false, ...over });
const copy = (kind: string, status: string, over: Record<string, unknown> = {}) => ({ kind, account: kind === 'argent' ? null : 'work', status, expires_at: null, killed_at: null, ...over });

describe('the Pack page with the mesh switch on', () => {
  test('a member shows real link state, its own switch, the removed logins and no reserve edit', async () => {
    member(true);
    view.mesh = { switch: 'on', links: [link('charlie', 'linked'), link('delta', 'unreachable', { dialed_by: 'peer', standing: false, on_demand: true }), link('ghost', 'linked')] };
    removed = { computers: [{ install_id: 'abcdef0123456789', removed_at: NOW - 3_600_000, state: 'removed', copies: [
      copy('claude', 'dies_by', { expires_at: NOW + 7_200_000 }), copy('codex', 'dies_by', { expires_at: NOW - 3_600_000 }), copy('argent', 'dead_now', { killed_at: NOW - 60_000 }), copy('claude', 'expiry_unknown'),
    ] }], argent_known: false, not_tracked: ['github'] };
    const root = await render();
    expect(root.querySelector('[data-computer-card="charlie"] [data-dial="linked"]')).not.toBeNull();
    expect(root.querySelector('[data-computer-card="ghost"]')).toBeNull();
    expect(root.querySelector('[data-computer-card="host:mesh-charlie"]')).toBeNull();
    expect(root.querySelector('[data-look] [data-rail="unreach"]')?.textContent).toContain('1');
    expect(root.querySelector('[data-line="mesh-self"]')?.textContent).toBe('this computer links with the other computers.');
    openComputer('charlie', 'link');
    await settle();
    const facts = root.querySelector('[data-act="mesh-link"]')?.textContent ?? '';
    expect(facts).toContain('linked');
    expect(facts).toContain('5 min ago');
    expect(facts).toContain('this computer');
    expect(facts).toContain('standing link');
    openComputer('delta', 'link');
    await settle();
    expect(root.querySelector('[data-act="mesh-link"]')?.textContent).toContain('opened for an action');
    expect(calls.filter((c) => c.path === '/pack/removed-logins')).toHaveLength(1);
    const rows = [...root.querySelectorAll('[data-sec="removed-logins"] [data-copy]')].map((r) => r.textContent?.replace(/\s+/g, ' ').trim());
    expect(rows).toHaveLength(4);
    expect(rows.join('|')).toMatch(/dies by \d+ nov \d\d:\d\d/);
    expect(rows.join('|')).toMatch(/ran out 1 hours? ago/);
    expect(rows.join('|')).toContain('dead now');
    expect(rows.join('|')).toContain('expiry unknown');
    expect(root.querySelector('[data-removed="abcdef0123456789"]')?.textContent).toContain('removed computer abcdef01');
    const text = root.querySelector('[data-sec="removed-logins"]')?.textContent ?? '';
    expect(text).toContain('argent is not running here');
    expect(text).toContain('github');
    const ed = await editor('alpha');
    expect(ed.querySelector('[data-pm="reserve-alpha-only"]')).not.toBeNull();
    expect(ed.querySelector('[data-pm="reserve-form"]')).toBeNull();
    expect(ed.querySelector('[data-rule]')).not.toBeNull();
  });

  test('the alpha shows the full pack refusal, the mesh removal words and the reserve form', async () => {
    view = { self: { ...SELF, role: 'main', main: null }, computers: [alphaEntry], invites: [], add_jobs: [], mesh: { switch: 'alpha', links: [] } };
    machines = [machine('me', { capabilities: ['pack.mesh_v1'], is_master: true }), machine('alpha', { is_master: false })];
    hostRows = [];
    machinesExtra = { roster_refusal: { code: 'pack_full', count: 66, limit: 64 } };
    const root = await render();
    expect(root.querySelector('[data-line="pack-full"]')?.textContent).toBe('the pack is full: 66 computers, 64 is the most. 2 are left out of the signed list until one is removed.');
    openComputer('alpha', 'overview');
    await settle();
    root.querySelector<HTMLButtonElement>('[data-act="remove"]')!.click();
    await settle();
    expect(root.querySelector('[data-act="remove-confirm"]')?.textContent).toContain('an estimate');
    const ed = await editor('alpha');
    expect(ed.querySelector('[data-pm="reserve-form"]')).not.toBeNull();
    expect(ed.querySelector('[data-pm="reserve-alpha-only"]')).toBeNull();
  });

  test('the link switch: the alpha flips it through one route, a member sees it read only, excluded needs a look, the age row is neutral', async () => {
    const charlie = (over: Record<string, unknown> = {}) => machine('charlie', { state: 'reported_connected', capabilities: ['pack.mesh_v1'], link_peers: true, mesh_capable: true, ...over });
    view = { self: { ...SELF, role: 'main', main: null }, computers: [alphaEntry], invites: [], add_jobs: [], mesh: { switch: 'alpha', links: [link('charlie', 'excluded')] } };
    machines = [machine('me', { capabilities: ['pack.mesh_v1'], is_master: true }), charlie()];
    hostRows = [];
    let root = await render();
    expect(root.querySelector('[data-look] [data-rail="unreach"]')?.textContent).toContain('1');
    openComputer('charlie', 'link');
    await settle();
    expect(root.querySelector('[data-act="mesh-link"]')?.textContent).toContain('since');
    expect(root.querySelector('[data-act="mesh-link"]')?.textContent).not.toContain('linked');
    const box = root.querySelector<HTMLElement>('[data-cmp="link-peers"]')!;
    expect(box).not.toBeNull();
    expect(box.hasAttribute('disabled')).toBe(false);
    expect(root.querySelector('[data-line="link-peers-readonly"]')).toBeNull();
    box.click();
    await settle();
    const sent = calls.filter((c) => c.path === '/pack/link-peers');
    expect(sent).toHaveLength(1);
    expect(sent[0]!.init?.method).toBe('PUT');
    expect(JSON.parse(String(sent[0]!.init?.body))).toEqual({ machine: 'charlie', on: false });
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    calls.length = 0;
    member(true);
    machines = [machine('me', { capabilities: ['pack.mesh_v1'] }), machine('alpha'), charlie()];
    view.mesh = { switch: 'on', links: [link('charlie', 'linked')] };
    root = await render();
    openComputer('charlie', 'link');
    await settle();
    const ro = root.querySelector<HTMLElement>('[data-cmp="link-peers"]')!;
    expect(ro.hasAttribute('disabled')).toBe(true);
    expect(root.querySelector('[data-line="link-peers-readonly"]')?.textContent).toBe('the alpha sets this.');
    expect(calls.some((c) => c.path === '/pack/link-peers')).toBe(false);
  });
});

describe('P20 9d: the mesh words on the Pack page', () => {
  const text = (el: Element | null): string => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();

  test('a member with no link row reads last heard from its status card, or not heard yet', async () => {
    member(true);
    view.mesh = { switch: 'on', links: [] };
    view.heard = { charlie: { at_ms: NOW - 240_000, age_s: 240, via: 'passed' } };
    const root = await render();
    expect(text(root.querySelector('[data-computer-card="charlie"]'))).toContain('last heard from 4 min ago');
    expect(text(root.querySelector('[data-computer-card="delta"]'))).toContain('no link now, no status card held');
  });

  test('a held over link reads held, not no link (10h)', async () => {
    member(true);
    view.mesh = { switch: 'on', links: [link('delta', 'held_over', { dialed_by: 'peer' })] };
    view.heard = {};
    const root = await render();
    const card = text(root.querySelector('[data-computer-card="delta"]'));
    expect(card).toContain('link held for now, no status card held');
    expect(card).not.toContain('no link now');
  });

  test('this computer says why its own switch is off, one true sentence per case', async () => {
    const own = async (over: Record<string, unknown>): Promise<string> => {
      for (const c of mounted.splice(0)) await unmount(c);
      document.body.replaceChildren();
      view = { self: SELF, computers: [alphaEntry], invites: [], add_jobs: [], mesh: { switch: 'off', links: [] } };
      machines = [machine('me', { capabilities: ['pack.mesh_v1'], ...over }), machine('alpha')];
      hostRows = [];
      machinesExtra = {};
      return text((await render()).querySelector('[data-line="mesh-self"]'));
    };
    expect(await own({ link_peers: null })).toBe('this computer does not link with the other computers: the signed list of computers it holds has no entry for it.');
    expect(await own({ link_peers: false, mesh_capable: false })).toBe('this computer does not link with the other computers: the signed list of computers does not mark it as able to link yet.');
    expect(await own({ link_peers: false, mesh_capable: true })).toBe('this computer does not link with the other computers. the alpha sets this.');
  });

  test('a refused newer list names the signer and the computers it would turn back on, and is absent otherwise', async () => {
    view = { self: SELF, computers: [alphaEntry], invites: [], add_jobs: [], mesh: { switch: 'alpha', links: [] } };
    machines = [machine('me', { capabilities: ['pack.mesh_v1'] }), machine('alpha'), machine('charlie', { capabilities: ['pack.mesh_v1'] })];
    hostRows = [];
    machinesExtra = { link_switch_refused: { signer: 'alpha', computers: ['charlie', 'iid-gone'] } };
    const warn = (await render()).querySelector('[data-line="mesh-switch-refused"]');
    expect(text(warn)).toBe('this computer is ignoring a newer computer list from alpha, because it would turn charlie, iid-gone back on after it was switched off. until you set the switch for charlie, iid-gone again on alpha, this computer links only with the alpha.');
    machinesExtra = {};
    expect((await render()).querySelector('[data-line="mesh-switch-refused"]')).toBeNull();
  });

  test('a link switch edit while the switches are unknown warns first and sends only after a yes', async () => {
    view = { self: { ...SELF, role: 'main', main: null }, computers: [alphaEntry], invites: [], add_jobs: [], mesh: { switch: 'alpha', links: [link('charlie', 'linked')] } };
    machines = [machine('me', { capabilities: ['pack.mesh_v1'], is_master: true }), machine('charlie', { state: 'reported_connected', capabilities: ['pack.mesh_v1'], link_peers: null, mesh_capable: null })];
    hostRows = [];
    machinesExtra = { link_switches_unknown: true };
    const root = await render();
    expect(root.querySelector('[data-line="mesh-unknown"]')).not.toBeNull();
    openComputer('charlie', 'link');
    await settle();
    expect(root.querySelector('[data-line="link-peers-unknown"]')).not.toBeNull();
    const box = root.querySelector<HTMLElement>('[data-cmp="link-peers"]')!;
    expect(box.hasAttribute('disabled')).toBe(false);
    vi.mocked(openModal).mockResolvedValueOnce(null as never);
    box.click();
    await settle();
    expect(calls.some((c) => c.path === '/pack/link-peers')).toBe(false);
    box.click();
    await settle();
    const sent = calls.filter((c) => c.path === '/pack/link-peers');
    expect(sent).toHaveLength(1);
    expect(JSON.parse(String(sent[0]!.init?.body))).toEqual({ machine: 'charlie', on: true });
    const body = vi.mocked(openModal).mock.calls.at(-1)?.[1] as { body: string };
    expect(body.body).toContain('every computer except charlie');
  });

  test('the reserve form follows ruling 8 in a mixed fleet', async () => {
    const reserve = async (id: string): Promise<string[]> => {
      const ed = await editor(id);
      return ['reserve-form', 'reserve-alpha-only'].filter((k) => ed.querySelector(`[data-pm="${k}"]`) !== null);
    };
    view = { self: { ...SELF, role: 'main', main: null }, computers: [], invites: [], add_jobs: [], mesh: { switch: 'alpha', links: [] } };
    machines = [machine('me', { capabilities: ['pack.mesh_v1'], is_master: true }), machine('old', { paired: true, snapshot: SNAP }), machine('new', { paired: true, snapshot: SNAP, capabilities: ['pack.mesh_v1'] })];
    hostRows = [];
    machinesExtra = {};
    await render();
    expect(await reserve('old')).toEqual(['reserve-form']);
    expect(await reserve('new')).toEqual(['reserve-form']);
    machinesExtra = { interim: true };
    await packMachines.refresh(true);
    await settle();
    expect(await reserve('old')).toEqual(['reserve-alpha-only']);
    machines = [machine('me', { capabilities: ['pack.mesh_v1'] }), machine('alpha', { snapshot: SNAP, capabilities: [] })];
    machinesExtra = {};
    await packMachines.refresh(true);
    await settle();
    expect(await reserve('alpha')).toEqual(['reserve-alpha-only']);
  });

  test('the removed logins reload on a removal, never on a reorder', async () => {
    member(true);
    view.mesh = { switch: 'on', links: [] };
    await render();
    const reads = (): number => calls.filter((c) => c.path === '/pack/removed-logins').length;
    const base = reads();
    expect(base).toBeGreaterThanOrEqual(1);
    machines = [...machines].reverse();
    await packMachines.refresh(true);
    await settle();
    expect(reads()).toBe(base);
    machines = machines.slice(1);
    await packMachines.refresh(true);
    await settle();
    expect(reads()).toBe(base + 1);
  });
});

describe('P20 10d: counts, choices and lines that decide what the owner reads', () => {
  const text = (el: Element | null): string => (el?.textContent ?? '').replace(/\s+/g, ' ').trim();

  test('the pack-full line is singular for one left out, plural for more, at both sites', async () => {
    member(true);
    view.mesh = { switch: 'on', links: [] };
    machinesExtra = { roster_refusal: { code: 'pack_full', count: 65, limit: 64 } };
    let root = await render();
    let lines = [...root.querySelectorAll('[data-line="pack-full"]')];
    expect(lines.length).toBe(2);
    for (const l of lines) expect(text(l)).toContain('1 is left out');
    expect(root.querySelector('[data-sets-full] [data-line="pack-full"]')).not.toBeNull();
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    machinesExtra = { roster_refusal: { code: 'pack_full', count: 67, limit: 64 } };
    root = await render();
    lines = [...root.querySelectorAll('[data-line="pack-full"]')];
    for (const l of lines) expect(text(l)).toContain('3 are left out');
  });

  test('the remove confirm names the right promise: a member removing a member, a member removing the alpha', async () => {
    member(true);
    view.mesh = { switch: 'on', links: [] };
    view.computers = [alphaEntry, { ...alphaEntry, install_id: 'charlie', label: 'charlie', role: 'member', fid: 'charliefid0', fid_short: 'charlf' }];
    const root = await render();
    openComputer('charlie', 'overview');
    await settle();
    root.querySelector<HTMLButtonElement>('[data-act="remove"]')!.click();
    await settle();
    expect(text(root.querySelector('[data-act="remove-confirm"]'))).toContain('the signed computer list is not changed from here');
    openComputer('alpha', 'overview');
    await settle();
    const btn = root.querySelector<HTMLButtonElement>('[data-act="remove"]');
    if (btn) { btn.click(); await settle(); }
    const t = text(root.querySelector('[data-act="remove-confirm"]'));
    expect(t).toContain('this computer leaves the pack');
    expect(t).not.toContain('signed computer list');
  });

  test('the how line reads linked over tls with its key, and drops the key clause when there is none', async () => {
    member(true);
    view.mesh = { switch: 'on', links: [] };
    let root = await render();
    expect(text(root.querySelector('[data-computer-card="alpha"]'))).toContain('linked over tls · key alphaf');
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    view.computers = [{ ...alphaEntry, fid_short: '' }];
    root = await render();
    const card = text(root.querySelector('[data-computer-card="alpha"]'));
    expect(card).toContain('linked over tls');
    expect(card).not.toContain('· key');
  });

  test('a grant scope reads in plain words, an unknown scope as it is', async () => {
    member(true);
    view.mesh = { switch: 'on', links: [] };
    grantRows = [{ grant_id: 'g1', peer_install_id: 'alpha', label: 'tool', scopes: ['machine', 'sessions', 'future-scope'], revoked_at: null }];
    peerRows = [{ key: 'alpha', label: 'alpha', peer_install_id: 'alpha', fid: 'alphafid000', initiator: true, state: 'connected', protocol: 1 }];
    const root = await render();
    openComputer('alpha', 'link');
    await settle();
    expect(text(root.querySelector('.pp-grants'))).toContain('computer info, sessions, future-scope');
  });
});
