/** @vitest-environment jsdom */
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import SettingsScreen from './SettingsScreen.svelte';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { SETTINGS, SETTINGS_SECTIONS, sectionKey, settingKey, settingsIn, settingsInGroup, type SettingDef } from './settings-registry';
import { searchSettings } from './settings-search';
import { tabsOf } from './screen-sections';
import { SettingsDoc, bindState, envMap, settingsDoc, type SettingsDocApi, type SettingsSummary } from './settings-doc.svelte';
import { setLocale, t } from '../i18n/index.svelte';

setLocale('en');

function summary(): SettingsSummary {
    return {
        workspace: { development_root: '~/dev', default_shell: '/bin/zsh', default_editor: 'code -w', env: { B: '2', A: '1' } },
        server_prefs: { bind_host: '', effective_bind_host: '127.0.0.1', tls_preferred: false },
        server: { host: '127.0.0.1', wildcard_bind: false },
        notifications: { enabled: false, ntfy_base_url: 'https://ntfy.sh', ntfy_topic: { configured: true }, slack_webhook_url: { configured: false } },
    };
}

function fakeApi(over: Partial<SettingsDocApi> = {}): SettingsDocApi & { patches: unknown[]; minutesSaved: number[] } {
    const patches: unknown[] = [];
    const minutesSaved: number[] = [];
    return {
        patches,
        minutesSaved,
        get: async () => summary(),
        patch: async (body) => {
            patches.push(body);
            return summary();
        },
        saveMinutes: async (m) => {
            minutesSaved.push(m);
            return true;
        },
        minutes: () => ({ value: 60, min: 5, max: 10080 }),
        ...over,
    };
}

describe('the registry', () => {
    test('every setting has a unique id and every section has at least one setting', () => {
        const ids = SETTINGS.map((s) => s.id);
        expect(new Set(ids).size).toBe(ids.length);
        for (const section of SETTINGS_SECTIONS) {
            if (section.screen) expect(settingsIn(section.id), section.id).toEqual([]);
            else expect(settingsIn(section.id).length, section.id).toBeGreaterThan(0);
        }
    });

    test('twelve sections, most reached-for first; launch profiles and keyboard shortcuts live inside; pack and plugins are not sections', () => {
        expect(SETTINGS_SECTIONS.map((s) => s.id)).toEqual([
            'account',
            'appearance',
            'sessions',
            'launch_profiles',
            'terminal',
            'notifications',
            'byoai',
            'log_processor',
            'remote',
            'general',
            'keys',
            'advanced',
        ]);
        expect(SETTINGS_SECTIONS.filter((s) => s.screen).map((s) => [s.id, s.screen])).toEqual([
            ['launch_profiles', 'launch-profiles'],
            ['keys', 'keys'],
        ]);
    });

    test('agent launch commands is a link to the launch profiles section', () => {
        const def = SETTINGS.find((s) => s.id === 'agent_commands');
        expect(def?.control).toEqual({ kind: 'link', action: 'open-wrappers' });
        for (const word of ['claude command', 'codex command', 'launch command']) {
            expect(t(settingKey('agent_commands', 'keywords')).toLowerCase()).toContain(word);
        }
    });

    test('every setting and section has its strings in the catalog', () => {
        for (const s of SETTINGS) {
            for (const part of ['label', 'help', 'keywords'] as const) {
                expect(t(settingKey(s.id, part)), `${s.id}.${part}`).not.toBe(settingKey(s.id, part));
            }
        }
        for (const section of SETTINGS_SECTIONS) {
            expect(t(sectionKey(section.id, 'label'))).not.toBe(sectionKey(section.id, 'label'));
            expect(t(sectionKey(section.id, 'hint'))).not.toBe(sectionKey(section.id, 'hint'));
            if (section.screen) expect(t(`settings.section.${section.id}.keywords`)).not.toBe(`settings.section.${section.id}.keywords`);
        }
    });
});

describe('search', () => {
    test('a blank query matches nothing, so the sections show', () => {
        expect(searchSettings('', t)).toEqual([]);
        expect(searchSettings('   ', t)).toEqual([]);
    });

    test('a synonym in the keywords finds its setting first', () => {
        expect(searchSettings('port', t)[0]?.setting.id).toBe('bind_address');
        expect(searchSettings('zsh', t)[0]?.setting.id).toBe('default_shell');
        expect(searchSettings('vscode', t)[0]?.setting.id).toBe('default_editor');
    });

    test('every word must match, so a second word narrows', () => {
        expect(searchSettings('ntfy', t).map((m) => m.setting.id)).toEqual(['notification_destinations']);
        expect(searchSettings('ntfy zzzz', t)).toEqual([]);
    });

    test('every setting is found by its own label', () => {
        for (const s of SETTINGS) {
            const hits = searchSettings(t(settingKey(s.id, 'label')), t).map((m) => m.setting.id);
            expect(hits, s.id).toContain(s.id);
        }
    });
});

describe('the document and its drafts', () => {
    let doc: SettingsDoc;
    let api: ReturnType<typeof fakeApi>;

    beforeEach(async () => {
        api = fakeApi();
        doc = new SettingsDoc(api);
        await doc.load();
    });

    test('a draft equal to what is stored is no draft at all', () => {
        doc.setDraft('default_editor', 'code -w --new');
        expect(doc.dirtyIds).toEqual(['default_editor']);
        doc.setDraft('default_editor', 'code -w');
        expect(doc.dirtyIds).toEqual([]);
    });

    test('an empty secret means keep, never clear', () => {
        const rows = SETTINGS as SettingDef[];
        rows.push({ id: 'fixture_secret', section: 'notifications', group: 'notifications.channels', saves: 'batch', control: { kind: 'secret', field: { group: 'notifications', key: 'ntfy_topic' } } });
        try {
            doc.setDraft('fixture_secret', '');
            expect(doc.dirtyIds).toEqual([]);
            doc.setDraft('fixture_secret', 'new-topic');
            expect(doc.patch()).toEqual({ notifications: { ntfy_topic: 'new-topic' } });
        } finally {
            rows.pop();
        }
    });

    test('the channels group is the destinations panel and no plaintext channel field is left in the registry', () => {
        expect(settingsInGroup('notifications.channels').map((s) => s.control.kind)).toEqual(['notify-destinations']);
        expect(settingsInGroup('notifications.routing').map((s) => s.control.kind)).toEqual(['notify-link', 'notify-matrix', 'notify-mutes', 'notify-sync']);
        expect(SETTINGS.filter((s) => s.control.kind === 'secret')).toEqual([]);
    });

    test('the env map goes whole, blank names dropped, and reordering is not a change', () => {
        doc.setDraft('environment', [{ name: 'A', value: '1' }, { name: 'B', value: '2' }, { name: '', value: 'x' }]);
        expect(doc.dirtyIds).toEqual([]);
        doc.setDraft('environment', [{ name: 'A', value: '1' }]);
        expect(doc.patch()).toEqual({ workspace: { env: { A: '1' } } });
        expect(envMap([{ name: ' C ', value: '3' }, { name: '', value: '' }])).toEqual({ C: '3' });
    });

    test('one save sends ONE patch with only what changed, then the minutes, and clears the drafts', async () => {
        doc.setDraft('default_editor', 'vim');
        doc.setDraft('bind_address', '0.0.0.0');
        doc.setDraft('auto_sleep_minutes', 30);
        expect(doc.dirtyIds.sort()).toEqual(['auto_sleep_minutes', 'bind_address', 'default_editor']);
        expect(await doc.save()).toBe(true);
        expect(api.patches).toEqual([{ workspace: { default_editor: 'vim' }, server_prefs: { bind_host: '0.0.0.0' } }]);
        expect(api.minutesSaved).toEqual([30]);
        expect(doc.dirtyIds).toEqual([]);
        expect(doc.status['default_editor']?.state).toBe('saved');
    });

    test('a refused save keeps every draft and says why', async () => {
        const failing = new SettingsDoc(fakeApi({ patch: async () => { throw new Error('must be executable'); } }));
        await failing.load();
        failing.setDraft('default_shell', '/nope');
        expect(await failing.save()).toBe(false);
        expect(failing.dirtyIds).toEqual(['default_shell']);
        expect(failing.saveError).toBe('must be executable');
        failing.discard();
        expect(failing.dirtyIds).toEqual([]);
    });

    test('minutes out of range keep save off rather than being sent', async () => {
        doc.setDraft('auto_sleep_minutes', 2);
        expect(doc.invalidIds).toEqual(['auto_sleep_minutes']);
        expect(await doc.save()).toBe(false);
        expect(api.minutesSaved).toEqual([]);
    });

    test('unread idle minutes: out of range keeps save off; in range saves through its own call', async () => {
        const saved: number[] = [];
        const unreadApi = fakeApi({
            unreadMinutes: () => 180,
            saveUnreadMinutes: async (m) => {
                saved.push(m);
                return true;
            },
        });
        const unreadDoc = new SettingsDoc(unreadApi);
        unreadDoc.setDraft('auto_sleep_unread_minutes', 2);
        expect(unreadDoc.invalidIds).toEqual(['auto_sleep_unread_minutes']);
        expect(await unreadDoc.save()).toBe(false);
        expect(saved).toEqual([]);
        unreadDoc.setDraft('auto_sleep_unread_minutes', 240);
        expect(unreadDoc.invalidIds).toEqual([]);
        expect(await unreadDoc.save()).toBe(true);
        expect(saved).toEqual([240]);
    });

    test('a switch writes its one key at once, with no draft', async () => {
        expect(await doc.applyToggle('prefer_tls', { group: 'server_prefs', key: 'tls_preferred' }, true)).toBe(true);
        expect(api.patches).toEqual([{ server_prefs: { tls_preferred: true } }]);
        expect(doc.dirtyIds).toEqual([]);
        expect(doc.status['prefer_tls']?.state).toBe('saved');
    });

    test('the bind address never calls a saved value in force', () => {
        expect(bindState('', null)).toBe('unmeasured');
        expect(bindState('', '127.0.0.1')).toBe('unset');
        expect(bindState('127.0.0.1', '127.0.0.1')).toBe('in-force');
        expect(bindState('0.0.0.0', '127.0.0.1')).toBe('pending');
    });
});

describe('the page', () => {
    interface Handle {
        show(): void;
        close(): void;
        isOpen(): boolean;
    }
    let handle: Handle | null = null;

    async function settle(): Promise<void> {
        for (let i = 0; i < 6; i += 1) await Promise.resolve();
        await tick();
        flushSync();
    }

    beforeEach(() => {
        vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(summary()), { status: 200 })));
        settingsDoc.discard();
    });

    afterEach(() => {
        if (handle) unmount(handle as unknown as Record<string, unknown>);
        handle = null;
        settingsDoc.discard();
        document.body.innerHTML = '';
        vi.unstubAllGlobals();
    });

    function render(embedded = true): HTMLElement {
        const target = document.createElement('div');
        document.body.append(target);
        handle = mount(SettingsScreen, { target, props: { embedded } }) as unknown as Handle;
        flushSync();
        return target;
    }

    function pickSection(root: HTMLElement, id: string): void {
        root.querySelector<HTMLButtonElement>(`.st-nav button[data-section="${id}"]`)!.click();
        flushSync();
    }

    test('no owner name row exists: the carnivore account handle replaced "your name" (#1200, U10)', async () => {
        expect(SETTINGS.map((s) => s.id)).not.toContain('owner_name');
        const root = render();
        await settle();
        for (const section of SETTINGS_SECTIONS.filter((s) => !s.screen)) {
            pickSection(root, section.id);
            await settle();
            expect(root.querySelector('[data-setting-id="owner_name"]'), section.id).toBeNull();
        }
    });

    test('every setting renders exactly once, in its own section only', async () => {
        const root = render();
        await settle();
        const seen = new Map<string, string[]>();
        for (const section of SETTINGS_SECTIONS.filter((s) => !s.screen)) {
            pickSection(root, section.id);
            await settle();
            const slugs = tabsOf(section.id);
            const ids: string[] = [];
            for (const slug of slugs.length > 1 ? slugs : [null]) {
                if (slug) {
                    root.querySelector<HTMLButtonElement>(`.oc-ptab[data-tab="${slug}"]`)!.click();
                    await settle();
                }
                ids.push(...[...root.querySelectorAll<HTMLElement>('[data-setting-id]')].map((el) => el.dataset.settingId!));
            }
            expect(new Set(ids).size, section.id).toBe(ids.length);
            expect(ids, section.id).toEqual(settingsIn(section.id).map((s) => s.id));
            for (const id of ids) seen.set(id, [...(seen.get(id) ?? []), section.id]);
        }
        expect([...seen.keys()].sort()).toEqual(SETTINGS.map((s) => s.id).sort());
        for (const [id, sections] of seen) expect(sections, id).toHaveLength(1);
    });

    test('the frame footer save is dimmed until a typed value waits, and discard takes the draft away', async () => {
        const root = render();
        await settle();
        pickSection(root, 'general');
        await settle();
        root.querySelector<HTMLButtonElement>('.oc-ptab[data-tab="paths"]')!.click();
        await settle();
        const save = root.querySelector<HTMLButtonElement>('.st-footer [data-settings-save]')!;
        expect(save.disabled).toBe(true);
        const input = root.querySelector<HTMLInputElement>('#setting-input-default_editor')!;
        input.value = 'vim';
        input.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        expect(save.disabled).toBe(false);
        expect(root.querySelector('.st-footer')?.textContent).toContain('1 unsaved change');
        expect(root.querySelector('[data-setting-id="default_editor"] .st-mark .oc-tag--accent')?.textContent).toBe('unsaved');
        root.querySelector<HTMLButtonElement>('.st-footer [data-settings-discard]')!.click();
        flushSync();
        expect(save.disabled).toBe(true);
        expect(root.querySelector('.st-footer')?.textContent).not.toContain('unsaved');
    });

    test('search filters across sections and Enter jumps to the best hit', async () => {
        const root = render();
        await settle();
        pickSection(root, 'general');
        const search = root.querySelector<HTMLInputElement>('.st-nav input[type="search"]')!;
        search.value = 'port';
        search.dispatchEvent(new Event('input', { bubbles: true }));
        flushSync();
        const hits = [...root.querySelectorAll<HTMLElement>('[data-hit]')].map((el) => el.dataset.hit);
        expect(hits[0]).toBe('bind_address');
        expect(root.querySelector('[data-setting-id]')).toBeNull();
        search.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
        await settle();
        expect(root.querySelector('button[data-section="remote"][aria-current="page"]')).not.toBeNull();
        expect(root.querySelector('[data-setting-id="bind_address"]')?.classList.contains('st-row--flash')).toBe(true);
    });

    test('picking a section pushes its link, a tab flip replaces it, and show() reads the link back (pages, not drawers)', async () => {
        window.history.replaceState(null, '', '/');
        const before = window.history.length;
        const root = render(false);
        handle!.show();
        await settle();
        expect(window.location.hash).toMatch(/^#settings\/[a-z_]+/);
        expect(window.history.length).toBe(before + 1);
        pickSection(root, 'terminal');
        expect(window.location.hash.startsWith('#settings/terminal')).toBe(true);
        expect(window.history.length).toBe(before + 2);
        const slugs = tabsOf('sessions');
        pickSection(root, 'sessions');
        expect(window.history.length).toBe(before + 3);
        root.querySelector<HTMLButtonElement>(`.oc-ptab[data-tab="${slugs[1]}"]`)!.click();
        await settle();
        expect(window.location.hash).toBe(`#settings/sessions/${slugs[1]}`);
        expect(window.history.length).toBe(before + 3);
        window.history.replaceState(null, '', '#settings/appearance');
        handle!.show();
        await settle();
        expect(root.querySelector('button[data-section="appearance"][aria-current="page"]')).not.toBeNull();
        expect(window.location.hash.startsWith('#settings/appearance')).toBe(true);
    });

    test('show() and close() put the page up and down, and Escape never closes it', async () => {
        const root = render(false);
        expect(handle!.isOpen()).toBe(false);
        handle!.show();
        await settle();
        expect(root.querySelector('.settings-page')).not.toBeNull();
        root.querySelector('.settings-page')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        flushSync();
        expect(handle!.isOpen()).toBe(true);
        handle!.close();
        flushSync();
        expect(handle!.isOpen()).toBe(false);
        expect(root.querySelector('.settings-page')).toBeNull();
    });
});
