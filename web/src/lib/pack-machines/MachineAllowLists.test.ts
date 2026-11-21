/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const puts: { path: string; body: unknown }[] = [];
vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'PUT') puts.push({ path, body: JSON.parse(init.body ?? 'null') });
    return {};
  },
}));

import { setLocale } from '../i18n/index.svelte';
import MachineAllowLists from './MachineAllowLists.svelte';
import type { AllowApi } from './allow-api';
import type { PackMachine } from './pack-machines-store.svelte';

setLocale('en');

const api: AllowApi = {
  get: async () => ({
    projects: [{ uid: 'p1', name: 'notes', company_uid: 'c1' }, { uid: 'p2', name: 'site', company_uid: null }],
    companies: [{ uid: 'c1', name: 'acme' }],
  }),
};
const machine = (self: boolean, projects: string[], companies: string[] = []): PackMachine => ({
  install_id: 'tower', label: 'tower', is_self: self, paired: true, state: 'connected', capabilities: [],
  snapshot: { restrictions: { allowed_projects: projects, allowed_companies: companies } },
} as unknown as PackMachine);

const mounted: ReturnType<typeof mount>[] = [];
const settle = async (): Promise<void> => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };
async function render(m: PackMachine): Promise<void> {
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(MachineAllowLists, { target, props: { machine: m, api } }));
  await settle();
  await settle();
}
const q = (sel: string): HTMLElement | null => document.body.querySelector<HTMLElement>(sel);
const box = (uid: string): HTMLInputElement => q(`[data-allow-project="${uid}"]`) as HTMLInputElement;
const save = (): HTMLButtonElement => q('[data-allow="save"]') as HTMLButtonElement;
const click = async (el: HTMLElement): Promise<void> => { el.click(); await settle(); await settle(); };

beforeEach(() => { puts.length = 0; });
afterEach(async () => {
  for (const c of mounted.splice(0)) await unmount(c);
  document.body.replaceChildren();
});

describe('the allow lists', () => {
  test('only the ticked ones with nothing ticked cannot be saved and says why', async () => {
    await render(machine(true, []));
    expect(save().disabled).toBe(true);
    await click(q('[data-allow="only"]')!);
    expect(q('[data-allow="reason"]')!.textContent).toContain('tick at least one');
    expect(save().disabled).toBe(true);
    await click(box('p1'));
    expect(q('[data-allow="reason"]')).toBeNull();
    expect(save().disabled).toBe(false);
    await click(save());
    expect(puts).toEqual([{ path: '/pack/machines/tower/restrictions', body: { allowed_projects: ['p1'], allowed_companies: [] } }]);
  });

  test('on a peer with a list, unticking is allowed, a new box is disabled, and emptying the list is refused', async () => {
    await render(machine(false, ['p1', 'p2']));
    expect(box('p1').disabled).toBe(false);
    expect((q('[data-allow="every"]') as HTMLButtonElement).disabled).toBe(true);
    await click(box('p2'));
    expect(save().disabled).toBe(false);
    await click(box('p1'));
    expect(q('[data-allow="reason"]')!.textContent).toContain('tick at least one');
    expect(save().disabled).toBe(true);
  });

  test('on a peer a box outside its stored list is disabled with the reason', async () => {
    await render(machine(false, ['p1']));
    expect(box('p2').disabled).toBe(true);
    expect(q('[data-allow-project="p2"]')!.closest('label')!.textContent).toContain('only that computer can add it');
  });

  test('ids this computer does not know show as one counted line and are kept on save', async () => {
    await render(machine(true, ['p1', 'gone1', 'gone2'], ['gonec']));
    expect(q('[data-allow="unknown-projects"]')!.textContent).toContain('2');
    expect(q('[data-allow="unknown-companies"]')!.textContent).toContain('1');
    await click(box('p1'));
    await click(save());
    expect(puts[0]!.body).toEqual({ allowed_projects: ['gone1', 'gone2'], allowed_companies: ['gonec'] });
  });
});
