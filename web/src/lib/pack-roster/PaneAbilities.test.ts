/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async () => ({ machines: [], settings: {} }),
}));

import { setLocale } from '../i18n/index.svelte';
import PaneAbilities from './PaneAbilities.svelte';
import type { AbilitiesApi } from './abilities-api';
import type { RosterComputer } from './roster-model';

setLocale('en');
const NOW = 1_700_000_000_000;
const can = { v: 1, rev: 'a'.repeat(16), probed_at: NOW / 1000 - 180, os: 'macos', os_version: '15.1', chip: 'm4', cores: 10, mem_gb: 32, gpus: [], tools: { git: true, blender: false }, ios_sim: false, brew: true, labels: ['fast disk'] };
const computer = (snapshot: Record<string, unknown> | null): RosterComputer => ({
  id: 'doom', name: 'doom', kind: 'pack', isSelf: true, machine: { install_id: 'doom', snapshot } } as unknown as RosterComputer);

let rescans = 0;
const api: AbilitiesApi = { rescan: async () => { rescans += 1; return { machine: 'doom', toolchain: {}, can: {}, fresh: false }; }, putLabels: async (_m, l) => l };
const mounted: ReturnType<typeof mount>[] = [];
const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
async function render(c: RosterComputer): Promise<void> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(PaneAbilities, { target, props: { c, onWork: () => {}, nowMs: NOW, api } }));
  await settle();
}
afterEach(async () => { for (const m of mounted.splice(0)) await unmount(m); document.body.replaceChildren(); rescans = 0; });

describe('PaneAbilities', () => {
  test('a snapshot with no can block says to update carnivore', async () => {
    await render(computer({ restrictions: {} }));
    expect(document.body.textContent).toContain('update carnivore on this computer to see what it has');
    expect(document.body.querySelector('[data-act="check-again"]')).toBeNull();
  });
  test('facts, the pegged line without the server text, the read lines and the checked line', async () => {
    await render(computer({ can, pressure: { pegged: true, since: 1_700_000_000, why: 'SERVER TEXT', busy_cores: 7, line: 6, cores: 8, run_queue_per_core: null, mem: null },
      restrictions: { may_host_agents: true, may_install_tools: false } }));
    const text = document.body.textContent ?? '';
    expect(text).toContain('macos 15.1');
    expect(text).toContain('7 of 8 cores busy, over the line of 6');
    expect(text).not.toContain('SERVER TEXT');
    expect(text).toContain('takes work: on');
    expect(text).toContain('may install tools: off');
    expect(document.body.querySelector('[data-pm="checked"]')?.textContent).toBe('checked 3 min ago');
  });
  test('check again calls the rescan; a skipped probe says less than a minute ago', async () => {
    await render(computer({ can, restrictions: { may_host_agents: true, may_install_tools: true } }));
    expect(document.body.querySelector('[data-act="check-again"]')?.getAttribute('data-btn')).toBe('secondary');
    (document.body.querySelector('[data-act="check-again"]') as HTMLElement).click();
    await settle(); await settle();
    expect(rescans).toBe(1);
    expect(document.body.querySelector('[data-pm="checked"]')?.textContent).toBe('checked less than a minute ago');
  });
});
