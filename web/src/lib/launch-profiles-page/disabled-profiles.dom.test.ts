/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import DisabledProfiles from './DisabledProfiles.svelte';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

afterEach(() => {
    document.body.innerHTML = '';
});

describe('disabled launch profiles', () => {
    test('a set-aside default shows its reason and the stand-in, with no control of its own', () => {
        const target = document.createElement('div');
        document.body.append(target);
        const handle = mount(DisabledProfiles, {
            target,
            props: {
                t,
                rows: [{ id: 'codex-bad', label: '<b>bad</b>', harness: 'codex', reason: '-c mcp_servers is owned by the app or another field', was_default: true, fallback_default: 'codex-spare' }],
            },
        });
        flushSync();
        const row = target.querySelector('[data-lp-disabled="codex-bad"]')!;
        expect(row.textContent).toContain('profile disabled: -c mcp_servers is owned by the app or another field');
        expect(row.textContent).toContain('codex-spare');
        expect(row.textContent).toContain('<b>bad</b>');
        expect(row.querySelector('b')).toBeNull();
        expect(row.querySelector('button')).toBeNull();
        unmount(handle);
    });
});
