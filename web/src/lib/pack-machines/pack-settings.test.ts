/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

let roster: unknown;
let pairs: unknown;

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => (path === '/pack/machines' ? roster : path === '/computers' ? pairs : {}),
}));

import { auth } from '../../opscenter/api/auth.svelte';
import ComputersPanel from '../computers/ComputersPanel.svelte';
import { computers } from '../computers/computers-store.svelte';
import { packMachines } from './pack-machines-store.svelte';
import { setLocale } from '../i18n/index.svelte';
import { filledCells, linkMarkFor, linkStateOf, loadPercent, reserveCells } from './pack-meter-math';
import { PACK_TABS, packTabOf } from '../pack-page/pack-hash';

setLocale('en');

const SNAP = {
  load: { cores: 10, load_1: 5, memory_percent: 58, disk_percent: 92 },
  battery: null,
  reserve: { level: 'away', cpu_pct: 10, mem_pct: 10, source: 'schedule', config: null },
  restrictions: {},
};
const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: false, is_master: false, paired: true,
  state: 'connected', capabilities: [], specs: null, snapshot: SNAP, age_seconds: 2, ...over });
const pair = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, host_key: null, transport: 'tls', role: 'member',
  state: 'connected', direction: 'both', fid: `${id}f`, fid_short: id, cert_sha256: null, joined_at: null, last_link_at: null,
  possible_duplicate_of: null, ...over });

const mounted: ReturnType<typeof mount>[] = [];
async function render(): Promise<HTMLElement> {
  roster = { master_install_id: 'hostb', self_install_id: 'hostb', settings: { placement_mode: 'stats', auto_distribute: false }, disagreement: null,
    machines: [machine('hosta'), machine('hostb', { is_self: true, is_master: true, state: 'self' })] };
  pairs = { self: { install_id: 'hostb', label: 'hostb', fid_short: 'ab', role: 'main', link: { state: 'listening', port: 1, join_open: false, addresses: [], code_paused_until: null }, main: null },
    computers: [pair('hosta')], invites: [], add_jobs: [] };
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(ComputersPanel, { target, props: {} }));
  await Promise.all([packMachines.refresh(true), computers.refresh(true)]);
  flushSync();
  return target;
}

beforeEach(() => { auth.state = 'signed-in'; });
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

describe('the pack computers list', () => {
  test('lists each computer once, this computer first, with the alpha badge and one this-computer icon', async () => {
    const root = await render();
    const rows = [...root.querySelectorAll('[data-machine]')].map((r) => r.getAttribute('data-machine'));
    expect(rows).toEqual(['hostb', 'hosta']);
    expect(root.querySelector('[data-machine="hostb"] [data-pm="master"]')!.textContent).toBe('alpha');
    expect(root.querySelector('[data-machine="hosta"] [data-pm="master"]')).toBeNull();
    expect(root.querySelectorAll('[data-mark="self"]').length).toBe(1);
    expect(root.querySelector('[data-mark="self"]')!.getAttribute('aria-label')).toBe('this computer');
    expect(root.textContent).not.toMatch(/this computer\s*this computer/);
    expect(root.textContent).not.toContain('master');
    expect(root.querySelector('[data-machine="hostb"] [data-pm="state-word"]')).toBeNull();
    expect(root.textContent).not.toContain('not seen yet');
    expect(root.querySelector('[data-machine="hostb"] [data-mark="link"]')).toBeNull();
    expect(root.querySelector('[data-machine="hosta"] [data-mark="link"]')!.getAttribute('data-link')).toBe('linked');
    expect(root.querySelector('[data-machine="hosta"] [data-pm="make-master"]')!.textContent).toBe('make alpha');
  });

  test('a meter fills the cells its percent says and holds the reserve at the top end', async () => {
    const root = await render();
    const cpu = root.querySelector('[data-machine="hosta"] .pk-meter')!;
    expect(cpu.querySelectorAll('[data-on="1"]').length).toBe(10);
    expect(cpu.querySelectorAll('[data-held="1"]').length).toBe(2);
    expect(cpu.getAttribute('data-level')).toBe('normal');
    const disk = root.querySelectorAll('[data-machine="hosta"] .pk-meter')[2]!;
    expect(disk.getAttribute('data-level')).toBe('critical');
    expect(disk.querySelectorAll('[data-held="1"]').length).toBe(0);
  });
});

describe('the meter and link arithmetic', () => {
  test('known values', () => {
    expect(filledCells(50)).toBe(10);
    expect(filledCells(null)).toBe(0);
    expect(reserveCells(10)).toBe(2);
    expect(loadPercent(5, 10)).toBe(50);
    expect(loadPercent(null, 10)).toBeNull();
    expect(linkStateOf('connected')).toBe('linked');
    expect(linkStateOf('waiting')).toBe('connecting');
    expect(linkStateOf('refused')).toBe('error');
    expect(linkStateOf('disconnected')).toBe('down');
    const snap = {};
    expect(linkMarkFor({ state: 'connected', snapshot: snap, age_seconds: 2 })).toBe('linked');
    expect(linkMarkFor({ state: 'connected', snapshot: null, age_seconds: null })).toBe('down');
    expect(linkMarkFor({ state: 'connected', snapshot: snap, age_seconds: 31 })).toBe('down');
    expect(linkMarkFor({ state: 'waiting', snapshot: null, age_seconds: null })).toBe('connecting');
  });
});

describe('the tab and hash mapping', () => {
  test('four tabs; #pack, #hosts and the old settings addresses reach the Pack page; old slugs map to the new tabs (ssh ones open the ssh filter)', () => {
    expect([...PACK_TABS]).toEqual(['computers', 'work', 'logins', 'skills']);
    expect(packTabOf('#pack')).toEqual({ tab: null, ssh: false });
    expect(packTabOf('#hosts')).toEqual({ tab: null, ssh: false });
    expect(packTabOf('#pack/skills')).toEqual({ tab: 'skills', ssh: false });
    expect(packTabOf('#settings/pack/work')).toEqual({ tab: 'work', ssh: false });
    expect(packTabOf('#settings/hosts/machines')).toEqual({ tab: 'computers', ssh: true });
    expect(packTabOf('#settings/hosts/pack')).toEqual({ tab: 'computers', ssh: false });
    expect(packTabOf('#hosts/machines')).toEqual({ tab: 'computers', ssh: true });
    expect(packTabOf('#ssh')).toEqual({ tab: 'computers', ssh: true });
    expect(packTabOf('#settings/hosts/computers')).toEqual({ tab: 'computers', ssh: false });
    expect(packTabOf('#settings/appearance')).toBeNull();
    expect(packTabOf('#packs')).toBeNull();
  });
});
