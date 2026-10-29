/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

let roster: unknown;
vi.mock('../api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async () => roster,
}));
vi.mock('./VizSettings.svelte', () => ({ default: () => {} }));

import { auth } from '../api/auth.svelte';
import { packMachines } from '../../lib/pack-machines/pack-machines-store.svelte';
import { setLocale } from '../../lib/i18n/index.svelte';
import type { ChartConfig } from '../cells/analytics/types';
import PackRenderer from './PackRenderer.svelte';
import { packModel } from './pack';

setLocale('en');

const CONFIG: ChartConfig = { id: 'p', revision: 1, title: 'pack', enabled: true, viz: 'pack', series: [], filters: {},
  range: { mode: 'global' }, display: { type: 'line' } };

function agent(id: number, name: string, cpu: number, rss: number) {
  return { session_id: id, session_uuid: `u${id}`, agent_id: null, name, cpu_pct: cpu, rss_mb: rss };
}

function snap(cores: number, load1: number, level: 'in_use' | 'away', reserveCpu: number, rows: ReturnType<typeof agent>[]) {
  const cpu = rows.reduce((a, r) => a + r.cpu_pct, 0);
  const rss = rows.reduce((a, r) => a + r.rss_mb, 0);
  return {
    load: { cores, load_1: load1, memory_percent: 50, disk_percent: 40 }, battery: { present: true, percent: 80, on_battery: false },
    reserve: { level, cpu_pct: reserveCpu, mem_pct: reserveCpu === 30 ? 20 : 10, source: 'schedule' }, restrictions: {},
    agents: { rows, truncated: 0, count: rows.length, carnivore: { cpu_pct: cpu, rss_mb: rss, agents: rows.length }, machine: { cpu_pct: cpu + 20, rss_mb: rss + 1000 } },
  };
}

function machine(id: string, over: Record<string, unknown>) {
  return { install_id: id, label: id, is_self: false, is_master: false, paired: true, state: 'connected', capabilities: [], specs: null, age_seconds: 1, ...over };
}

const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => { auth.state = 'signed-in'; });
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

describe('the pack view', () => {
  test('two machines render per-box and overall totals that add up, the master marked and the reserve line drawn', async () => {
    roster = { master_install_id: 'mac', self_install_id: 'mac', settings: { placement_mode: 'stats', auto_distribute: false }, disagreement: null,
      machines: [
        machine('mac', { is_self: true, is_master: true, state: 'self', snapshot: snap(10, 8, 'in_use', 30, [agent(1, 'alpha', 150, 2048), agent(2, 'beta', 50, 1024)]) }),
        machine('hosta', { snapshot: snap(8, 2, 'away', 10, [agent(3, 'gamma', 100, 512)]) }),
      ] };
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(PackRenderer, { target, props: { config: CONFIG, instance: 'i', tier: 'full' } }));
    await packMachines.refresh(true);
    flushSync();

    expect(target.querySelectorAll('[data-pack-box]').length).toBe(2);
    expect(target.querySelectorAll('[data-pack-master]').length).toBe(1);
    expect(target.querySelector('[data-pack-box="mac"] [data-pack-master]')).not.toBeNull();
    expect(target.querySelector('[data-pack-box="mac"] [data-pack-line]')!.getAttribute('data-pack-line')).toBe('70');
    expect(target.querySelector('[data-pack-box="hosta"] [data-pack-line]')!.getAttribute('data-pack-line')).toBe('90');
    expect(target.querySelector('[data-pack-box="mac"] [data-pack-level]')!.textContent).toBe('in use');
    expect(target.querySelector('[data-pack-box="hosta"] [data-pack-level]')!.textContent).toBe('away');
    expect(target.querySelector('[data-pack-box="mac"] [data-pack-reserve]')!.textContent).toBe('reserve 30% cpu, 20% mem');
    expect(target.querySelector('[data-pack-box="mac"] [data-pack-sum] dd')!.textContent).toBe('2, 2 cores, 3072 mb');
    expect(target.querySelector('[data-pack-box="mac"]')!.className).toContain('--over');
    expect(target.querySelector('[data-pack-box="hosta"]')!.className).not.toContain('--over');
    const sums = [...target.querySelectorAll('[data-pack-sum] dd')].map((e) => e.textContent ?? '');
    expect(sums[0]).toContain('2 ');
    expect(sums[1]).toContain('1 ');
    expect(target.querySelector('[data-pack-total="agents"]')!.textContent).toContain('3 agents');
    expect(target.querySelector('[data-pack-total="cores"]')!.textContent).toContain('3 / 18');
    expect(target.querySelector('[data-pack-total="mem"]')!.textContent).toContain('3584');
    expect(target.querySelector('[data-pack-agent="3"]')!.textContent).toContain('hosta');
  });

  test('a machine with no snapshot says its state and stays out of the totals; nothing is zero', () => {
    const model = packModel({ master_install_id: 'mac', self_install_id: 'mac', settings: { placement_mode: 'stats', auto_distribute: false }, disagreement: null,
      machines: [machine('mac', { is_self: true, is_master: true, state: 'self', snapshot: snap(4, 1, 'away', 10, [agent(1, 'a', 100, 100)]) }),
        machine('hosta', { snapshot: null, state: 'disconnected' })] } as never);
    const hosta = model.boxes.find((b) => b.installId === 'hosta')!;
    expect([hosta.live, hosta.cores, hosta.loadPct, hosta.agentCount]).toEqual([false, null, null, null]);
    expect(model.totals).toMatchObject({ machines: 2, reporting: 1, silent: 1, agents: 1, agentCores: 1 });
  });
});
