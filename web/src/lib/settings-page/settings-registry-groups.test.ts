import { describe, expect, test } from 'vitest';
import { setLocale, t } from '../i18n/index.svelte';
import {
    groupKey,
    groupOfSlug,
    groupsIn,
    SETTINGS,
    SETTINGS_SECTIONS,
    settingsInGroup,
    slugOf,
} from './settings-registry';

setLocale('en');

describe('settings groups', () => {
    test('every group id is namespaced under its own setting\'s section', () => {
        for (const setting of SETTINGS) {
            expect(setting.group.startsWith(`${setting.section}.`)).toBe(true);
        }
    });

    test('a group slug is the part after the section, and names its group back', () => {
        for (const setting of SETTINGS) {
            const slug = slugOf(setting.group);
            expect(slug).not.toContain('.');
            expect(groupOfSlug(setting.section, slug)).toBe(setting.group);
        }
        expect(groupOfSlug('sessions', 'nope')).toBeNull();
    });

    test('groupsIn returns each group exactly once, in first-appearance order', () => {
        for (const section of SETTINGS_SECTIONS) {
            const groups = groupsIn(section.id);
            expect(new Set(groups).size).toBe(groups.length);
            const expected: string[] = [];
            for (const s of SETTINGS) {
                if (s.section === section.id && !expected.includes(s.group)) expected.push(s.group);
            }
            expect(groups).toEqual(expected);
        }
    });

    test('settingsInGroup partitions a section: every setting of a section is in exactly one of its groups', () => {
        for (const section of SETTINGS_SECTIONS) {
            const bySection = SETTINGS.filter((s) => s.section === section.id);
            const viaGroups = groupsIn(section.id).flatMap((g) => settingsInGroup(g));
            expect(viaGroups.map((s) => s.id).sort()).toEqual(bySection.map((s) => s.id).sort());
        }
    });

    test('every group used has a non-empty label and hint in the catalog', () => {
        const seen = new Set(SETTINGS.map((s) => s.group));
        for (const group of seen) {
            const label = t(groupKey(group, 'label'));
            const hint = t(groupKey(group, 'hint'));
            expect(label).not.toBe(groupKey(group, 'label'));
            expect(hint).not.toBe(groupKey(group, 'hint'));
            expect(label.length).toBeGreaterThan(0);
            expect(hint.length).toBeGreaterThan(0);
        }
    });

    test('sessions & agents groups: auto-sleep, then agents (the time machine tab and the conversation index tab were removed 2026-10-12)', () => {
        expect(groupsIn('sessions')).toEqual(['sessions.auto_sleep', 'sessions.agents']);
        expect(groupsIn('sessions')).not.toContain('sessions.time_machine');
        expect(groupOfSlug('sessions', 'time_machine')).toBeNull();
        expect(groupOfSlug('sessions', 'conversation_index')).toBeNull();
        expect(settingsInGroup('sessions.auto_sleep').map((s) => s.id)).toEqual([
            'auto_sleep', 'auto_sleep_minutes', 'auto_sleep_unread_blocks', 'auto_sleep_unread_minutes',
        ]);
        expect(settingsInGroup('sessions.agents').map((s) => s.id)).toEqual(['agent_commands', 'agent_gate', 'mcp_server']);
    });

    test('notifications groups: the owner specified delivery then channels; web push (#164) follows them', () => {
        expect(groupsIn('notifications')).toEqual(['notifications.delivery', 'notifications.channels', 'notifications.routing', 'notifications.web_push', 'notifications.messaging']);
        expect(settingsInGroup('notifications.routing').map((s) => s.id)).toEqual(['notification_link', 'notification_matrix', 'notification_mutes', 'notification_sync']);
        expect(settingsInGroup('notifications.web_push').map((s) => s.id)).toEqual(['web_push']);
        expect(settingsInGroup('notifications.delivery').map((s) => s.id)).toEqual([
            'toast_style',
        ]);
        expect(settingsInGroup('notifications.channels').map((s) => s.id)).toEqual([
            'notification_destinations',
        ]);
    });

    test('appearance groups: colors, agent rows, status bar, control center, motion; the header shortcuts are gone', () => {
        expect(groupsIn('appearance')).toEqual([
            'appearance.colors', 'appearance.sidebar', 'appearance.status_bar', 'appearance.control_center', 'appearance.motion',
        ]);
        expect(SETTINGS.map((s) => s.id)).not.toContain('header_quicklinks');
        expect(settingsInGroup('appearance.status_bar').map((s) => s.id)).toEqual(['foot_bar_layout', 'foot_bar_items']);
        expect(settingsInGroup('appearance.control_center').map((s) => s.id)).toEqual(['foot_bar_layout_open']);
        expect(settingsInGroup('appearance.motion').map((s) => s.id)).toEqual(['animations']);
    });
});
