/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import SettingControl from './SettingControl.svelte';
import { SETTINGS } from './settings-registry';
import { catalogAccount } from '../drawer-hud/catalog-account.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

vi.mock('../carnivore-account/account-store.svelte', () => ({ refreshAccount: async () => undefined }));
const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let comp: Record<string, unknown> | null = null;
function render() {
    const def = SETTINGS.find((s) => s.id === 'carnivore_account')!;
    expect(def.control.kind).toBe('carnivore-account');
    const target = document.createElement('div');
    document.body.appendChild(target);
    comp = mount(SettingControl, { target, props: { def, t } as never }) as never;
    flushSync();
}
afterEach(() => {
    if (comp) unmount(comp as never);
    comp = null;
    document.body.innerHTML = '';
    catalogAccount.facts = null;
});

describe('settings account section', () => {
    it('signed in: handle, account buttons and sign out show inline', () => {
        catalogAccount.facts = { signedIn: true, handle: 'ada-lovelace', login: 'a@x.test', email: 'a@x.test', provider: 'google' };
        render();
        expect(document.querySelector('[data-account-handle]')?.textContent).toBe('ada-lovelace');
        expect(document.querySelector('[data-account-signout]')).not.toBeNull();
        expect(document.body.textContent).toContain('download my data');
    });
    it('signed out: the sign-in button shows', () => {
        catalogAccount.facts = { signedIn: false } as never;
        render();
        expect(document.querySelector('[data-account-signin]')).not.toBeNull();
    });
});
