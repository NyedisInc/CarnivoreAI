/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

let consentPending = true;

vi.mock('../../opscenter/api/auth.svelte', async (original) => ({
  ...(await original<Record<string, unknown>>()),
  authFetch: async (path: string) => path === '/pack/relay-approval'
    ? { computers: [{ install_id: 'iid-b', label: 'studio', answer: null, pending: true }] }
    : { mode: null, answered: false, may_receive_credentials: false, accepted: [], pending: consentPending ? ['k'] : [],
        offers: [{ key: 'k', sender: 'iid-a', sender_label: 'a', account_key: 'k', label: 'k', accepted: false, pending: consentPending }] },
}));

import { auth } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import { relayApproval } from './relay-approval-store.svelte';
import { relayConsent } from './relay-consent-store.svelte';
import RelayApprovalPopup from './RelayApprovalPopup.svelte';
import RelayConsentPopup from './RelayConsentPopup.svelte';

setLocale('en');
const mounted: ReturnType<typeof mount>[] = [];
beforeEach(() => { auth.state = 'signed-in'; });
afterEach(() => { mounted.splice(0).forEach((m) => unmount(m)); document.body.innerHTML = ''; });

test('the approval popup waits behind a pending consent popup, then shows', async () => {
  consentPending = true;
  await Promise.all([relayConsent.refresh(true), relayApproval.refresh(true)]);
  for (const C of [RelayConsentPopup, RelayApprovalPopup]) { const target = document.createElement('div'); document.body.append(target); mounted.push(mount(C, { target })); }
  flushSync();
  expect(document.querySelectorAll('[role="alertdialog"]').length).toBe(1);
  expect(document.querySelector('[data-rc="desc"]')).not.toBeNull();
  consentPending = false;
  await relayConsent.refresh(true);
  flushSync();
  expect(document.querySelectorAll('[role="alertdialog"]').length).toBe(1);
  expect(document.querySelector('[data-ra="desc"]')).not.toBeNull();
});
