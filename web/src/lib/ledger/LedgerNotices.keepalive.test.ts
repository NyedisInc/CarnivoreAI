/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';

import LedgerNotices from './LedgerNotices.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('the note names itself and opens to the catalog copy', () => {
    handle = mount(LedgerNotices, {
        target: document.body,
        props: { loop: null, failure: null, loading: false, isEmpty: false, now: 0, t },
    });
    const btn = document.querySelector('.ledger-keepalive .info-tip__btn') as HTMLButtonElement;
    expect(btn.getAttribute('aria-label')).toBe('how account keep-alive works');
    expect(document.querySelector('.ledger-keepalive__label')?.textContent).toBe(
        'how account keep-alive works',
    );
    expect(document.querySelector('[role="note"]')).toBeNull();
    btn.click();
    flushSync();
    const note = document.querySelector('[role="note"]')?.textContent ?? '';
    expect(note).toContain('claude logins expire every 8 hours');
    expect(note).toContain('login revoked, sign in again');
    expect(note).not.toContain('Mac');
});
