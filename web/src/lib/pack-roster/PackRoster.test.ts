/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; init?: RequestInit }[] = [];
let view: Record<string, unknown>;
let machines: unknown[];
let hostRows: unknown[];

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    const method = init?.method ?? 'GET';
    if (path === '/computers' && method === 'GET') return structuredClone(view);
    if (path === '/pack/machines' && method === 'GET') return { machines: structuredClone(machines), settings: {}, tracks_master: false };
    if (path === '/hosts' && method === 'GET') return { status: 'ok', hosts: structuredClone(hostRows) };
    if (path === '/federation/peers' || path === '/federation/pending-pairs') return [];
    if (path === '/federation/discovered') return { discovered: [], state: 'on' };
    if (path === '/federation/settings') return { advertise: true, state: 'on', pack_name: null };
    return {};
  },
}));
vi.mock('../modal', () => ({ openModal: vi.fn(async () => true) }));

import { auth } from '../../opscenter/api/auth.svelte';
import { computers } from '../computers/computers-store.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import { setLocale } from '../i18n/index.svelte';
import PackRoster from './PackRoster.svelte';
import RosterActions from './RosterActions.svelte';
import { hosts, peers, discovered } from './roster-store.svelte';
import { openComputer, rosterUi } from './roster-ui.svelte';

setLocale('en');

const SELF = (role: string) => ({ install_id: 'me', label: 'studio', fid_short: 'ab12cd', role,
  link: { state: 'listening', port: 8443, join_open: false, addresses: [], code_paused_until: null },
  main: role === 'member' ? { label: 'hosta', state: 'connected', last_link_at: null, reachable_note: false } : null });
const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: id === 'me', is_master: id === 'me', paired: id !== 'me',
  state: 'ok', capabilities: [], specs: null, snapshot: null, age_seconds: 5, ...over });
const entry = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, host_key: null, transport: 'ssh', role: 'member', state: 'connected', direction: 'both',
  fid: `${id}fid000`, fid_short: `${id}fid`.slice(0, 6), cert_sha256: null, joined_at: null, last_link_at: new Date().toISOString(), possible_duplicate_of: null, ...over });
const host = (key: string, over: Record<string, unknown> = {}) => ({ key, label: key, local: false, ssh_target: `acme@${key}`, ssh_port: null, socket: 'carnivore-remote', enabled: true, session_count: 0,
  probe_state: 'ok', probe_detail: null, probed_at: null, tmux_path: null, tmux_version: '3.4', login_path: null, agent_paths: null, login_shell: '/bin/zsh', machine_id: null,
  remote_carnivore: null, computer_install_id: null, created_at: '', updated_at: '', ...over });

const mounted: ReturnType<typeof mount>[] = [];
async function render(role = 'main', entryOver: Record<string, unknown> = {}): Promise<HTMLElement> {
  view = { self: SELF(role), computers: [entry('hosta', entryOver)], invites: [], add_jobs: [] };
  machines = [machine('me'), machine('hosta')];
  hostRows = [host('hosta', { computer_install_id: 'hosta' }), host('forge')];
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(PackRoster, { target, props: {} }), mount(RosterActions, { target, props: {} }));
  await Promise.all([computers.refresh(true), packMachines.refresh(true), hosts.refresh(true), peers.refresh(true), discovered.refresh(true)]);
  await settle();
  return target;
}

async function settle(): Promise<void> {
  for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 0));
  flushSync();
}

beforeEach(() => {
  auth.state = 'signed-in';
  calls.length = 0;
  Object.assign(rosterUi, { filter: 'all', q: '', openId: null, tab: 'overview', mode: null, settings: true, landSsh: false, view: 'cards' });
});
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

describe('the Pack roster', () => {
  test('lists computers and ssh hosts once, and a computer shows its ssh host on its ssh tab', async () => {
    const root = await render();
    const ids = [...root.querySelectorAll('[data-computer-card]')].map((e) => e.getAttribute('data-computer-card'));
    expect(ids).toEqual(expect.arrayContaining(['me', 'hosta', 'host:forge']));
    expect(ids.filter((i) => i === 'hosta')).toHaveLength(1);
    openComputer('hosta', 'ssh');
    await settle();
    expect(root.querySelector('.pp-ssh')?.textContent).toContain('acme@hosta');
    expect(root.querySelector('[data-act="match"]')).not.toBeNull();
  });

  test('the settings panel folds into the gear and reopens from it', async () => {
    const root = await render();
    expect(root.querySelector('[data-panel="settings"]')).not.toBeNull();
    expect(root.querySelector('[data-act="settings"]')).toBeNull();
    root.querySelector<HTMLButtonElement>('[data-roster-key="sets-close"]')!.click();
    await settle();
    expect(root.querySelector('[data-panel="settings"]')).toBeNull();
    root.querySelector<HTMLButtonElement>('[data-act="settings"]')!.click();
    await settle();
    expect(root.querySelector('[data-panel="settings"]')).not.toBeNull();
  });

  test('a joined computer shows membership and a standalone one shows join a pack, never both', async () => {
    let root = await render('member');
    expect(root.querySelector('[data-sec="membership"]')).not.toBeNull();
    expect(root.querySelector('[data-sec="join"]')).toBeNull();
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    root = await render('standalone');
    expect(root.querySelector('[data-sec="join"]')).not.toBeNull();
    expect(root.querySelector('[data-sec="membership"]')).toBeNull();
  });

  test('the needs a look group is absent at zero and shows a red row when a computer stops answering', async () => {
    let root = await render();
    expect(root.querySelector('[data-look]')).toBeNull();
    for (const c of mounted.splice(0)) await unmount(c);
    document.body.replaceChildren();
    root = await render('main', { state: 'disconnected', dial: { state: 'unreachable', since: '4 min ago' } });
    expect(root.querySelector('[data-look] [data-rail="unreach"]')?.textContent).toContain('1');
  });

  test('the wolf button confirms, then makes that computer the leader through PUT /pack/master', async () => {
    const root = await render();
    root.querySelector<HTMLButtonElement>('[data-computer-card="hosta"] [data-act="makeleader"]')!.click();
    await settle();
    const put = calls.find((c) => c.path === '/pack/master' && c.init?.method === 'PUT');
    expect(put).toBeTruthy();
    expect(JSON.parse(String(put!.init!.body))).toEqual({ machine: 'hosta' });
  });
});
