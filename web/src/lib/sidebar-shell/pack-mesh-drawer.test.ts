/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

let machines: unknown[] = [];
const imported = vi.hoisted(() => vi.fn());

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => {
    if (path === '/pack/machines') return { machines: structuredClone(machines), settings: {}, tracks_master: false };
    if (path === '/computers') return { computers: [], mesh: { links: [{ install_id: 'b', state: 'unreachable', since: null, dialed_by: 'this', standing: true, on_demand: false }] } };
    return {};
  },
}));
vi.mock('../computers/computers-store.svelte', async (original) => { imported(); return original(); });

import { auth } from '../../opscenter/api/auth.svelte';
import { packMachines } from '../pack-machines/pack-machines-store.svelte';
import { setLocale } from '../i18n/index.svelte';
import { MESH_CAP } from '../pack-roster/roster-model';
import { meshLinkOf, packSource, watchPack } from './pack-source.svelte';
import PackSection from './PackSection.svelte';
import type { PackPlan, PackRowPlan } from './plan';

setLocale('en');
const row = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: id === 'a', is_master: id === 'alpha', paired: false, state: 'reported_connected', capabilities: id === 'a' ? [MESH_CAP] : [], specs: null, snapshot: null, age_seconds: 1, ...over });

let handle: ReturnType<typeof mount> | null = null;
beforeEach(() => {
  auth.state = 'signed-in';
  document.body.innerHTML = '';
  (globalThis as Record<string, unknown>).ResizeObserver = class { observe(): void {} disconnect(): void {} };
});
afterEach(() => { if (handle) unmount(handle); handle = null; });

function plan(m: unknown): PackPlan {
  const r = m as { install_id: string; label: string };
  const rows = [{ id: r.install_id, label: r.label, alpha: false, self: false, link: 'linked', machine: m, off: false, lightHtml: '' }] as unknown as PackRowPlan[];
  return { type: 'pack', key: 'pack', open: true, density: 'compact', count: 1, rows,
    heading: { toggle: 'group', key: 'pack', bandKind: 'reserved', expanded: true, bodyId: 'b', title: 't', label: 'pack', iconHtml: '', ledHtml: '', pickedIconHtml: '', rollupHtml: '' } } as unknown as PackPlan;
}

describe('the drawer with the mesh switch', () => {
  it('on: the computers store lands, the mesh store fills and the row says reported word then the link word', async () => {
    machines = [row('a'), row('b')];
    await packMachines.refresh(true);
    watchPack();
    flushSync();
    for (let i = 0; i < 20 && imported.mock.calls.length === 0; i += 1) await new Promise((r) => setTimeout(r, 5));
    expect(imported).toHaveBeenCalled();
    expect(imported).toHaveBeenCalledTimes(1);
    const m = packSource().find((x) => x.install_id === 'b')!;
    for (let i = 0; i < 50 && meshLinkOf(m) === null; i += 1) await new Promise((r) => setTimeout(r, 10));
    expect(meshLinkOf(m)?.state).toBe('unreachable');
    const target = document.body.appendChild(document.createElement('div'));
    handle = mount(PackSection, { target, props: { p: plan(m) } });
    flushSync();
    expect(target.querySelector('[data-pack-computer="b"] .sb-pack-row__state')?.textContent).toBe('connected to alpha, unreachable');
  });
});
