/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

let doc: unknown;
let putFails = false;
const puts: unknown[] = [];

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (_path: string, init?: { method?: string; body?: string }) => {
    if (init?.method === 'PUT') {
      puts.push(JSON.parse(init.body ?? '{}'));
      if (putFails) throw new Error('refused');
      return doc;
    }
    return doc;
  },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import RelayConsentPopup from './RelayConsentPopup.svelte';
import { relayConsent } from './relay-consent-store.svelte';
import { setLocale } from '../i18n/index.svelte';

setLocale('en');

const offer = (key: string, over: Record<string, unknown> = {}) => ({ key, sender: 'iid-a', sender_label: 'studio', account_key: key.split(':')[1],
  label: key.split(':')[1], accepted: false, pending: true, ...over });
const view = (over: Record<string, unknown> = {}) => ({ mode: null, answered: false, may_receive_credentials: false, accepted: [],
  offers: [offer('iid-a:work'), offer('iid-a:home')], pending: ['iid-a:work', 'iid-a:home'], ...over });

const mounted: ReturnType<typeof mount>[] = [];
async function render(over: Record<string, unknown> = {}): Promise<HTMLElement> {
  doc = view(over);
  puts.length = 0;
  putFails = false;
  await relayConsent.refresh(true);
  const target = document.createElement('div');
  document.body.append(target);
  mounted.push(mount(RelayConsentPopup, { target }));
  flushSync();
  return target;
}
const q = (el: HTMLElement, sel: string) => el.querySelector<HTMLElement>(sel)!;
const settle = async () => { await new Promise((r) => setTimeout(r, 0)); flushSync(); };

beforeEach(() => { auth.state = 'signed-in'; });
afterEach(() => { mounted.splice(0).forEach((m) => unmount(m)); document.body.innerHTML = ''; });

describe('relay consent popup', () => {
  test('is an alertdialog with no close button, and Escape and an outside click do not close it', async () => {
    const el = await render();
    const overlay = q(el, '[role="alertdialog"]');
    expect(overlay.getAttribute('aria-modal')).toBe('true');
    expect(el.querySelector('.modal-close, [data-modal-close]')).toBeNull();
    overlay.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    overlay.click();
    flushSync();
    expect(el.querySelector('[role="alertdialog"]')).not.toBeNull();
    expect(el.querySelectorAll('[data-rc-key]').length).toBe(2);
  });

  test('yes is disabled while nothing is ticked', async () => {
    const el = await render();
    expect((q(el, '[data-rc="yes"]') as HTMLButtonElement).disabled).toBe(false);
    q(el, '[data-rc="all"]').click();
    flushSync();
    expect((q(el, '[data-rc="yes"]') as HTMLButtonElement).disabled).toBe(true);
  });

  test('yes with every box and the all box sends mode all', async () => {
    const el = await render();
    q(el, '[data-rc="yes"]').click();
    await settle();
    expect(puts).toEqual([{ mode: 'all' }]);
  });

  test('yes with a subset sends mode list, keeping keys already accepted under a list answer', async () => {
    const el = await render({ mode: 'list', accepted: ['iid-b:old'], offers: [offer('iid-a:work'), offer('iid-a:home'), offer('iid-b:old', { accepted: true, pending: false })], pending: ['iid-a:work', 'iid-a:home'] });
    q(el, '[data-rc-key="iid-a:home"]').click();
    flushSync();
    q(el, '[data-rc="yes"]').click();
    await settle();
    expect(puts).toEqual([{ mode: 'list', accounts: ['iid-b:old', 'iid-a:work'] }]);
  });

  test('no sends mode none', async () => {
    const el = await render();
    q(el, '[data-rc="no"]').click();
    await settle();
    expect(puts).toEqual([{ mode: 'none' }]);
  });

  test('a failed PUT keeps the popup open with an inline error', async () => {
    const el = await render();
    putFails = true;
    q(el, '[data-rc="yes"]').click();
    await settle();
    expect(q(el, '[data-rc="error"]').textContent).toContain('refused');
    expect(el.querySelector('[role="alertdialog"]')).not.toBeNull();
  });
});
