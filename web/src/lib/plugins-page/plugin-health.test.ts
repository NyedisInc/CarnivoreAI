/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';
import { CATALOGS, DEFAULT_LOCALE } from '../../../../client/js/i18n/catalogs.js';
import ClaudeCodeHealth from './ClaudeCodeHealth.svelte';
import PluginHealthLine from './PluginHealthLine.svelte';
import { buttonLabelOf, claudeCodeRows, contractOf, healthOf, reasonOf, toneOf, wordOf, type HealthReport, type HealthRow } from './plugin-health';
import { canRun, runHealthButton, type HealthDoors } from './plugin-health-actions';
import { createPluginHealth } from './plugin-health.svelte';

const messages = (CATALOGS[DEFAULT_LOCALE]?.messages ?? {}) as Record<string, string>;
const t = (key: string): string => messages[key] ?? `MISSING:${key}`;

const row = (over: Partial<HealthRow>): HealthRow => ({ id: 'clock', kind: 'feature', source: 'built_in', word: 'on', reason: null, button: 'turn_off', version: null, data_bytes: 0, ...over });
const plugin = (cplugId: string, publisher: string | null = null) => ({ cplugId, publisher });
const REPORT: HealthReport = {
    rows: [
        row({ id: 'clock' }),
        row({ id: 'acme/gonecat', kind: 'plugin', source: 'catalog', word: 'held', reason: 'revoked', button: 'open_catalog' }),
        row({ id: 'local/devtool', kind: 'claude_code_plugin', source: 'folder', word: 'needs_approval', reason: 'changed_on_disk', button: 'review' }),
    ],
};

let mounted: Record<string, unknown> | null = null;
afterEach(() => { if (mounted) unmount(mounted); mounted = null; document.body.innerHTML = ''; });

async function draw(component: never, props: Record<string, unknown>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(component, { target, props: { t, ...props } });
    await tick(); flushSync();
    return target;
}

describe('the words', () => {
    test('every word, reason and button the server names has a catalog sentence', () => {
        const words: HealthRow['word'][] = ['on', 'off', 'needs_approval', 'held'];
        const reasons = ['new_install', 'grant_waiting', 'code_changed', 'changed_on_disk', 'safe_mode', 'third_party_off', 'sideload_off', 'revoked',
            'index_expired', 'trust_refused', 'needs_plugin', 'folder_unreadable', 'folder_missing', 'manifest_invalid', 'install_record_missing',
            'crashed', 'unavailable', 'runtime_down'];
        const buttons = ['turn_off', 'turn_on', 'review', 'leave_safe_mode', 'turn_on_third_party', 'turn_on_developer', 'open_catalog', 'turn_on_needed_plugin', 'show_log'];
        for (const word of words) expect(wordOf(row({ word }), t)).not.toContain('MISSING');
        for (const reason of reasons) expect(reasonOf(row({ reason }), t), reason).not.toContain('MISSING');
        for (const button of buttons) expect(buttonLabelOf(row({ button }), t), button).not.toContain('MISSING');
    });

    test('an unknown reason or button reads as nothing, and the tone follows the word', () => {
        expect(reasonOf(row({ reason: 'from_a_newer_server' }), t)).toBeNull();
        expect(buttonLabelOf(row({ button: 'delete_data' }), t)).toBeNull();
        expect(buttonLabelOf(row({ button: null }), t)).toBeNull();
        expect([toneOf({ word: 'on' }), toneOf({ word: 'off' }), toneOf({ word: 'held' }), toneOf({ word: 'needs_approval' })]).toEqual(['on', 'off', 'warn', 'warn']);
    });

    test('a feature row reads its feature twin, in lowercase plain words', () => {
        expect(messages['features.page.health.reason.needs_plugin']).toContain('feature');
        for (const [key, text] of Object.entries(messages).filter(([k]) => k.includes('.page.health.'))) {
            expect(text, key).toBe(text.toLowerCase());
            expect(text, key).not.toMatch(/[–—]/);
        }
    });
});

describe('the lookup', () => {
    test('a page plugin finds its row by cplug id or publisher/name, and a Claude Code row is never a page plugin', () => {
        expect(healthOf(REPORT, plugin('clock'))?.word).toBe('on');
        expect(healthOf(REPORT, plugin('gonecat', 'acme'))?.reason).toBe('revoked');
        expect(healthOf(REPORT, plugin('devtool', 'local'))).toBeUndefined();
        expect(healthOf(null, plugin('clock'))).toBeUndefined();
        expect(claudeCodeRows(REPORT).map((r) => r.id)).toEqual(['local/devtool']);
        expect(claudeCodeRows(null)).toEqual([]);
    });
});

describe('the store', () => {
    test('leaving safe mode puts {on: false} to the safe-mode route and reads the report again', async () => {
        const fetcher = vi.fn(async (route: string) => (route === '/cplug-owner/health' ? REPORT : {}));
        const health = createPluginHealth(fetcher as never);
        await health.leaveSafeMode();
        expect(fetcher.mock.calls[0]).toEqual(['/cplugs/safe-mode', { method: 'PUT', body: JSON.stringify({ on: false }) }]);
        expect(fetcher.mock.calls[1]?.[0]).toBe('/cplug-owner/health');
        expect(health.report).toEqual(REPORT);
    });

    test('reads on call only, keeps the last good report on a failed read, and the newest answer wins', async () => {
        vi.useFakeTimers();
        const fetcher = vi.fn(async () => REPORT) as never;
        const health = createPluginHealth(fetcher);
        vi.advanceTimersByTime(10 * 60 * 1000);
        expect(fetcher).not.toHaveBeenCalled();
        await health.load();
        expect(health.report).toEqual(REPORT);
        expect(health.claudeCode).toHaveLength(1);
        const failing = createPluginHealth((async () => { throw new Error('offline'); }) as never);
        await failing.load();
        expect(failing.report).toBeNull();
        let release: (r: HealthReport) => void = () => {};
        const slow = new Promise<HealthReport>((resolve) => { release = resolve; });
        const answers = [slow, Promise.resolve(REPORT)];
        const racing = createPluginHealth((async () => answers.shift()) as never);
        const first = racing.load();
        await racing.load();
        release({ rows: [] });
        await first;
        expect(racing.report).toEqual(REPORT);
        vi.useRealTimers();
    });
});

describe('the buttons', () => {
    const doors = () => ({
        toggle: vi.fn<HealthDoors['toggle']>(), openPane: vi.fn<HealthDoors['openPane']>(), select: vi.fn<HealthDoors['select']>(),
        openDeveloperZone: vi.fn<HealthDoors['openDeveloperZone']>(), openCatalog: vi.fn<HealthDoors['openCatalog']>(),
        leaveSafeMode: vi.fn<HealthDoors['leaveSafeMode']>(async () => {}),
    });
    const subject = { itemId: 'cplug:clock', blockedBy: ['base'] };

    test('each button runs its one door; a button with no subject or no door is not offered', async () => {
        const d = doors();
        await runHealthButton({ button: 'turn_off' }, subject, d);
        await runHealthButton({ button: 'turn_on' }, subject, d);
        await runHealthButton({ button: 'review' }, subject, d);
        await runHealthButton({ button: 'turn_on_needed_plugin' }, subject, d);
        await runHealthButton({ button: 'turn_on_developer' }, null, d);
        await runHealthButton({ button: 'open_catalog' }, null, d);
        await runHealthButton({ button: 'leave_safe_mode' }, null, d);
        expect(d.toggle.mock.calls).toEqual([['cplug:clock', false], ['cplug:clock', true]]);
        expect(d.openPane).toHaveBeenCalledWith('cplug:clock', 'permissions');
        expect(d.select).toHaveBeenCalledWith('cplug:base');
        expect(d.openDeveloperZone).toHaveBeenCalledTimes(1);
        expect(d.openCatalog).toHaveBeenCalledTimes(1);
        expect(d.leaveSafeMode).toHaveBeenCalledTimes(1);
        const calls = d.toggle.mock.calls.length;
        await runHealthButton({ button: 'turn_on' }, null, d);
        await runHealthButton({ button: 'delete_data' }, subject, d);
        expect(d.toggle.mock.calls.length).toBe(calls);
        expect(canRun({ button: 'turn_on_needed_plugin' }, { itemId: 'cplug:x', blockedBy: [] })).toBe(false);
        expect(canRun({ button: null }, subject)).toBe(false);
    });
});

describe('the drawing', () => {
    test('a line draws the word, the reason and the button, and the button reports a press', async () => {
        const onAct = vi.fn();
        const root = await draw(PluginHealthLine as never, { row: REPORT.rows[1], canAct: true, onAct });
        const line = root.querySelector('[data-plugin-health="acme/gonecat"]') as HTMLElement;
        expect(line.dataset.healthWord).toBe('held');
        expect(line.textContent).toContain('held');
        expect(line.textContent).toContain(messages['plugins.page.health.reason.revoked']);
        (line.querySelector('[data-health-button="open_catalog"]') as HTMLButtonElement).click();
        expect(onAct).toHaveBeenCalledTimes(1);
    });

    test('a line names the plugin contract version when the report has one, and nothing when it has none', async () => {
        const root = await draw(PluginHealthLine as never, { row: { ...REPORT.rows[1], api_version: 1 }, canAct: false, onAct: () => {} });
        const note = root.querySelector('[data-health-api-version]') as HTMLElement;
        expect(note.dataset.healthApiVersion).toBe('1');
        expect(note.textContent).toBe(messages['plugins.page.health.contract']);
        expect(contractOf({ ...REPORT.rows[1], api_version: 1 }, (k, p) => `${k}:${String(p?.version)}`)).toBe('plugins.page.health.contract:1');
        expect(contractOf({ ...REPORT.rows[1], api_version: null }, t)).toBeNull();
        unmount(mounted!); mounted = null; document.body.innerHTML = '';
        const none = await draw(PluginHealthLine as never, { row: REPORT.rows[1], canAct: false, onAct: () => {} });
        expect(none.querySelector('[data-health-api-version]')).toBeNull();
    });

    test('no button is drawn when the page has no door for it', async () => {
        const root = await draw(PluginHealthLine as never, { row: REPORT.rows[1], canAct: false, onAct: () => {} });
        expect(root.querySelector('[data-health-button]')).toBeNull();
    });

    test('the Claude Code list draws one line per plugin and nothing when there are none', async () => {
        const onAct = vi.fn();
        const root = await draw(ClaudeCodeHealth as never, { rows: claudeCodeRows(REPORT), canAct: () => true, onAct });
        expect(root.querySelectorAll('[data-plugin-health]')).toHaveLength(1);
        expect(root.querySelector('[data-health-word="needs_approval"]')?.textContent).toContain(messages['plugins.page.health.reason.changed_on_disk']);
        unmount(mounted!); mounted = null; document.body.innerHTML = '';
        const empty = await draw(ClaudeCodeHealth as never, { rows: [], canAct: () => true, onAct });
        expect(empty.querySelector('[data-claude-code-health]')).toBeNull();
    });
});
