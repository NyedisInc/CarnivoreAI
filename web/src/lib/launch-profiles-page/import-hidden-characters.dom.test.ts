/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ImportProfileModal from './ImportProfileModal.svelte';
import type { ImportPreview, LaunchProfilesApi } from './api';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

const FLAG = '--add-dir=/tmp/‮evil​';

const PREVIEW = {
    profile: { id: 'claude-x', label: 'x', harness: 'claude' },
    sha256: 'c'.repeat(64),
    parts: [{ kind: 'flags', text: FLAG }],
    exists: false,
    existing_is_default: false,
    endpoint_connection_missing: false,
} as unknown as ImportPreview;

/** Let pending promises and effects run. */
async function settle(): Promise<void> {
    for (let i = 0; i < 10; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

afterEach(() => {
    document.body.innerHTML = '';
});

describe('import modal part text', () => {
    test('a flag value with U+202E and U+200B is shown with both written out', async () => {
        const api = { importPreview: async () => PREVIEW } as unknown as LaunchProfilesApi;
        const target = document.createElement('div');
        document.body.append(target);
        const handle = mount(ImportProfileModal, { target, props: { api, t, close: () => undefined } });
        flushSync();

        const box = document.querySelector<HTMLTextAreaElement>('#lp-import-text')!;
        box.value = '{}';
        box.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        document.querySelector<HTMLButtonElement>('[data-lp-import-check]')!.click();
        await settle();

        const shown = document.querySelector('.lp-import__script')!.textContent ?? '';
        expect(shown).toBe('--add-dir=/tmp/\\u{202e}evil\\u{200b}');
        expect(shown).not.toContain('‮');
        expect(shown).not.toContain('​');
        unmount(handle);
    });
});
