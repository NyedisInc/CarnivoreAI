/** @vitest-environment jsdom */
import { describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import SettingsSearchResults from './SettingsSearchResults.svelte';
import { SETTINGS, type SettingDef } from './settings-registry';
import { t, setLocale } from '../i18n/index.svelte';

setLocale('en');

function settingById(id: string): SettingDef {
    const found = SETTINGS.find((s) => s.id === id);
    if (!found) throw new Error(`fixture setting missing: ${id}`);
    return found;
}

describe('a search hit\'s section/group breadcrumb', () => {
    test('two hits from the same section but different groups read differently', () => {
        const target = document.createElement('div');
        const matches = [
            { setting: settingById('toast_style'), score: 8 },
            { setting: settingById('notification_destinations'), score: 8 },
        ];
        const handle = mount(SettingsSearchResults, {
            target,
            props: { t, query: 'x', matches, onJump: () => {} },
        });
        flushSync();

        const sections = Array.from(target.querySelectorAll('.st-hit__section')).map((el) => el.textContent);
        expect(sections).toEqual([
            'notifications › delivery',
            'notifications › destinations',
        ]);
        sections.forEach((text) => {
            expect(text).toContain('notifications');
            expect(text).toMatch(/delivery|destinations/);
        });

        unmount(handle);
    });
});
