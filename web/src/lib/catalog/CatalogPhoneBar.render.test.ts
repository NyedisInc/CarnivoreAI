/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import CatalogPhoneBar from './CatalogPhoneBar.svelte';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

let handle: ReturnType<typeof mount> | null = null;
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('the tools row is a frame-density region of small text acts and a square ? key', () => {
    const noop = (): void => {};
    handle = mount(CatalogPhoneBar, { target: document.body, props: { sortKey: 'featured', onSort: noop, refreshing: false, onRefresh: noop, onPublish: noop, t } });
    flushSync();
    const row = document.querySelector('.catalog-phonebar__row--tools') as HTMLElement;
    expect(row.getAttribute('data-btn-density')).toBe('frame');
    const acts = [...row.querySelectorAll('[data-warez-act]:not([data-keys-button])')];
    expect(acts.length).toBe(2);
    expect(acts.every((b) => b.getAttribute('data-size') === 'sm')).toBe(true);
    const keys = row.querySelector('[data-keys-button]') as HTMLElement;
    expect(keys.getAttribute('data-size')).toBe('icon');
    expect(keys.getAttribute('aria-label')).toBe(t('warez.keys.button_label'));
    expect(keys.textContent?.trim()).toBe('?');
});
