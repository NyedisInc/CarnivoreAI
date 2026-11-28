/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const calls: { path: string; init?: RequestInit }[] = [];
let approval: unknown[] = [];
let refuseYes = false;
const machine = (id: string, over: Record<string, unknown> = {}) => ({ install_id: id, label: id, is_self: id === 'me', is_master: false, paired: id !== 'me', state: 'connected', capabilities: id === 'me' ? ['pack.mesh_v1'] : [], specs: null, snapshot: null, age_seconds: 1, ...over });

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string, init?: RequestInit) => {
    calls.push({ path, init });
    if (path === '/pack/machines') return { machines: [machine('me'), machine('alpha'), machine('here')], settings: {} };
    if (path === '/pack/relay-approval' && (init?.method ?? 'GET') === 'GET') return { computers: structuredClone(approval) };
    if (path === '/pack/relay') return { accounts: {} };
    if (path.startsWith('/pack/relay-approval/') && init?.method === 'PUT' && refuseYes) throw new Error('the computer list cannot be read right now, so that yes was not saved. try again in a moment.');
    if (path.includes('accounts') || path.includes('ledger')) return [{ id: 'work', name: 'work' }];
    return {};
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import { packMachines } from './pack-machines-store.svelte';
import { claudeAccounts, packRelay } from './pack-relay-store.svelte';
import { relayApproval } from './relay-approval-store.svelte';
import PackRelayBlock from './PackRelayBlock.svelte';

setLocale('en');
const mounted: ReturnType<typeof mount>[] = [];
const settle = async (): Promise<void> => { for (let i = 0; i < 4; i++) await new Promise((r) => setTimeout(r, 0)); flushSync(); };
async function render(rows: unknown[]): Promise<HTMLElement> {
  approval = rows;
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(PackRelayBlock, { target, props: {} }));
  (claudeAccounts as unknown as { push: (v: unknown) => void }).push([{ id: 'work', name: 'work' }] as never);
  await Promise.all([packMachines.refresh(true), relayApproval.refresh(true), packRelay.refresh(true)]);
  await settle();
  return target;
}
const row = (root: HTMLElement, id: string): HTMLElement => root.querySelector<HTMLElement>(`[data-relay-approval="${id}"]`)!;
const box = (root: HTMLElement, id: string): HTMLElement => row(root, id).querySelector<HTMLElement>('[data-relay="approval"]')!;
const puts = (): unknown[] => calls.filter((c) => c.init?.method === 'PUT' && c.path.startsWith('/pack/relay-approval/')).map((c) => JSON.parse(String(c.init?.body)));

beforeEach(() => { auth.state = 'signed-in'; calls.length = 0; refuseYes = false; });
afterEach(async () => { for (const c of mounted.splice(0)) await unmount(c); document.body.replaceChildren(); });

describe('relay approval rows', () => {
  test('an alpha row with no alpha yes is enabled and mixed, and a click records a no', async () => {
    const root = await render([{ install_id: 'alpha', label: 'alpha', answer: null, pending: false, decided_by: 'alpha', alpha_yes: false }]);
    expect(box(root, 'alpha').hasAttribute('disabled')).toBe(false);
    expect(box(root, 'alpha').getAttribute('aria-checked')).toBe('mixed');
    expect(box(root, 'alpha').getAttribute('role')).toBe('checkbox');
    expect(row(root, 'alpha').textContent).toContain('once the alpha says yes');
    box(root, 'alpha').click();
    await settle();
    expect(puts()).toEqual([{ answer: 'no' }]);
  });

  test('a refused yes shows the words it was refused with (10a-4 S4)', async () => {
    refuseYes = true;
    const root = await render([{ install_id: 'alpha', label: 'alpha', answer: 'no', pending: false, decided_by: 'alpha', alpha_yes: true }]);
    box(root, 'alpha').click();
    await settle();
    expect(root.querySelector('[data-pm="approval-error"]')?.textContent).toContain('cannot be read right now');
  });

  test('a recorded no reads unchecked with its own words, and a click sends a yes', async () => {
    const root = await render([{ install_id: 'alpha', label: 'alpha', answer: 'no', pending: false, decided_by: 'alpha', alpha_yes: false }]);
    expect(box(root, 'alpha').getAttribute('aria-checked')).toBe('false');
    expect(row(root, 'alpha').textContent).toContain('your no here wins over the alpha');
    box(root, 'alpha').click();
    await settle();
    expect(puts()).toEqual([{ answer: 'yes' }]);
  });

  test('a row decided here keeps checked meaning an answer of yes', async () => {
    const root = await render([{ install_id: 'here', label: 'here', answer: null, pending: false, decided_by: 'here' }]);
    expect(box(root, 'here').getAttribute('aria-checked')).toBe('false');
    expect(box(root, 'here').getAttribute('role')).toBe('switch');
    expect(box(root, 'here').hasAttribute('disabled')).toBe(false);
  });
});
