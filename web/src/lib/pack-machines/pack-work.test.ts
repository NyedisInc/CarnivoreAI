/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

let roster: Record<string, unknown>;

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => (path === '/pack/machines' ? roster : path === '/pack/tracks-master' ? { tracks_master: true } : {}),
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import { packMachines, tracksMaster } from './pack-machines-store.svelte';
import PackWorkTab from './PackWorkTab.svelte';
import { closeMigrate, openMigrate } from '../pack-migrate/migrate-store.svelte';

setLocale('en');

const CFG = { in_use: { cpu_pct: 20, mem_pct: 25 }, away: { cpu_pct: 5, mem_pct: 6 }, schedule: { in_use_from: '08:00', in_use_to: '18:00', days: [0, 1] }, keyboard_rule: { enabled: false, idle_minutes: 10 } };
const snap = { load: { cores: 10, load_1: 5, memory_percent: 58, disk_percent: 40 }, battery: null,
  reserve: { level: 'away', cpu_pct: 5, mem_pct: 6, source: 'schedule', config: CFG },
  restrictions: { may_host_agents: true, may_receive_projects: true, may_install_tools: false, may_receive_credentials: false, may_update_carnivore: true, max_agents: 3, allowed_projects: [], allowed_companies: [] } };
const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: false, is_master: false, paired: true, state: 'connected',
  capabilities: [], specs: null, snapshot: snap, age_seconds: 2, ...over });

const mounted: ReturnType<typeof mount>[] = [];
async function render(mode: string): Promise<HTMLElement> {
  roster = { master_install_id: 'nostromo', self_install_id: 'nostromo', settings: { placement_mode: mode, auto_distribute: false }, disagreement: null,
    machines: [machine('nostromo', { is_self: true, is_master: true, state: 'self' }), machine('studio')] };
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(PackWorkTab, { target, props: {} }));
  await Promise.all([packMachines.refresh(true), tracksMaster.refresh(true)]);
  flushSync();
  return target;
}

beforeEach(() => { auth.state = 'signed-in'; });
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

describe('pack > work', () => {
  test('the status strip names the alpha, counts computers online and says whether this one follows', async () => {
    const root = await render('stats');
    expect(root.querySelector('[data-pm="master-line"]')!.textContent).toContain('nostromo');
    expect(root.querySelector('[data-pw="count"]')!.textContent).toBe('2 computers, 2 online');
    expect(root.querySelector('[data-pw="follows"]')!.textContent).toBe('follows the alpha');
  });

  test('the placement model pickers show only while enhanced placement is on', async () => {
    expect((await render('stats')).querySelector('[data-pm="placement-model"]')).toBeNull();
    document.body.replaceChildren();
    const on = await render('enhanced');
    expect(on.querySelector('[data-pm="placement-model"] [data-ai="route-connection"]')).not.toBeNull();
    const inputs = [...on.querySelectorAll<HTMLInputElement>('[data-pm="placement-model"] input')];
    expect(inputs.map((i) => i.value || i.placeholder)).toEqual(['default: ai routing', 'default: a cheap model']);
  });

  test('each computer row shows its real reserve and restriction values', async () => {
    const root = await render('stats');
    const row = root.querySelector('[data-machine="studio"]')!;
    const text = row.textContent!;
    expect(text).toContain('now away: keeps 5% cpu 6% mem free');
    expect(text).toContain('in use: 20% cpu 25% mem');
    expect(text).toContain('most agents: 3');
    expect(row.querySelector('[data-on="false"]')!.textContent).toBe('may install tools');
  });

  test('the move button stays disabled until a project or company and a target computer are both picked', async () => {
    const root = await render('stats');
    const go = root.querySelector<HTMLButtonElement>('[data-pm="migrate-go"]')!;
    const pick = root.querySelector<HTMLSelectElement>('[data-pm="migrate-pick"]')!;
    const target = root.querySelector<HTMLSelectElement>('[data-pm="migrate-target"]')!;
    expect(go.disabled).toBe(true);
    pick.insertAdjacentHTML('beforeend', '<option value="p:demo">demo</option>');
    pick.value = 'p:demo';
    pick.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    expect(go.disabled).toBe(true);
    target.value = 'studio';
    target.dispatchEvent(new Event('change', { bubbles: true }));
    flushSync();
    expect(go.disabled).toBe(false);
  });

  test('the row move button hides while the move panel is open and returns when it closes', async () => {
    const root = await render('stats');
    expect(root.querySelector('[data-pm="migrate-go"]')).not.toBeNull();
    openMigrate({ kind: 'project', name: 'demo' });
    flushSync();
    expect(root.querySelector('[data-pm="migrate-go"]')).toBeNull();
    closeMigrate();
    flushSync();
    expect(root.querySelector('[data-pm="migrate-go"]')).not.toBeNull();
  });
});
