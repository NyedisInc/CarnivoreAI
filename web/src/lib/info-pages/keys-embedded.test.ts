/** @vitest-environment jsdom */
import { afterEach, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import SettingsScreenSection from '../settings-page/SettingsScreenSection.svelte';

let handle: Record<string, unknown> | null = null;
afterEach(() => {
    if (handle) unmount(handle);
    handle = null;
    document.body.innerHTML = '';
});

test('embedded keys view has no inset bar or lone label, and still lists its sections', () => {
    const target = document.createElement('div');
    document.body.append(target);
    handle = mount(SettingsScreenSection, { target, props: { kind: 'keys' } });
    flushSync();
    expect(target.querySelector('.oc-page__inset-end')).toBeNull();
    expect(target.querySelector('.oc-page__bar')).toBeNull();
    expect(target.textContent).not.toMatch(/\bkeys\b\s*$/);
    expect(target.querySelectorAll('[data-keys-section]').length).toBeGreaterThan(0);
});
