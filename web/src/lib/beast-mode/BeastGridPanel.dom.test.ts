/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import BeastGridPanel from './BeastGridPanel.svelte';
import { gridMatrix, scopeSchema, TRUST_SCOPE_KEY } from './grid-model';
import { rulesWith, RULES } from './grid-fixture';
import { BEAST_SETTINGS_HASH } from './settings-link';
import { groupOfSlug, settingById } from '../settings-page/settings-registry';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { authFetch } from '../../opscenter/api/auth.svelte';

const t = (key: string): string => key;
let mounted: ReturnType<typeof mount> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function open(answer: (init?: RequestInit) => unknown): Promise<{ calls: { path: string; init?: RequestInit }[] }> {
    const calls: { path: string; init?: RequestInit }[] = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        calls.push({ path, init });
        return answer(init);
    }) as unknown as typeof authFetch;
    mounted = mount(BeastGridPanel, { target: document.body, props: { t, fetcher } });
    await vi.waitFor(() => expect(document.querySelector('[data-settings-matrix]')).not.toBeNull());
    return { calls };
}

const box = (key: string): HTMLElement => document.querySelector(`[data-setting="${key}"] [role="checkbox"]`) as HTMLElement;

describe('beast mode grid panel', () => {
    test('reads the rules, draws a row per kind and the read only rows, and the defaults as ticked', async () => {
        await open(() => RULES);
        expect(document.querySelectorAll('[data-matrix-row][data-locked="0"]').length).toBe(7);
        expect(document.querySelectorAll('[data-matrix-row][data-locked="1"]').length).toBe(9);
        expect(box('folderTrustOff').getAttribute('aria-checked')).toBe('true');
        expect(box('agentWritesOff').getAttribute('aria-checked')).toBe('false');
        expect(box('agentWritesOn').getAttribute('aria-checked')).toBe('true');
        expect(document.querySelector('[data-matrix-row][data-locked="1"] [role="checkbox"]')).toBeNull();
    });

    test('unticking a safe box writes that one key, then shows what the server holds', async () => {
        const { calls } = await open((init) => (init?.method === 'PUT' ? rulesWith({ folderTrustOff: false }) : RULES));
        box('folderTrustOff').click();
        await vi.waitFor(() => expect(calls.some((c) => c.init?.method === 'PUT')).toBe(true));
        const put = calls.find((c) => c.init?.method === 'PUT')!;
        expect(put.path).toBe('/beast-mode/rules');
        expect(JSON.parse(String(put.init!.body))).toEqual({ cells: { folderTrustOff: false } });
        await vi.waitFor(() => expect(box('folderTrustOff').getAttribute('aria-checked')).toBe('false'));
    });

    test('ticking a beast off box that auto approves asks first and saves nothing until confirmed', async () => {
        const { calls } = await open((init) => (init?.method === 'PUT' ? rulesWith({ agentWritesOff: true }) : RULES));
        box('agentWritesOff').click();
        flushSync();
        expect(document.querySelector('[data-matrix-ask="agentWritesOff"]')).not.toBeNull();
        expect(calls.filter((c) => c.init?.method === 'PUT')).toEqual([]);
        (document.querySelector('[data-matrix-ask-confirm]') as HTMLElement).click();
        await vi.waitFor(() => expect(calls.some((c) => c.init?.method === 'PUT')).toBe(true));
        expect(JSON.parse(String(calls.find((c) => c.init?.method === 'PUT')!.init!.body))).toEqual({ cells: { agentWritesOff: true } });
    });

    test('a refusal shows under its row and the stored value stays on screen', async () => {
        await open((init) => {
            if (init?.method === 'PUT') throw new ApiError('refused', 422, null, { detail: 'not a beast mode box' });
            return RULES;
        });
        box('folderTrustOff').click();
        await vi.waitFor(() => expect(document.querySelector('[role="alert"]')?.textContent).toContain('not a beast mode box'));
        expect(box('folderTrustOff').getAttribute('aria-checked')).toBe('true');
    });

    test('the folder scope writes trust_scope', async () => {
        const { calls } = await open((init) => (init?.method === 'PUT' ? rulesWith({}, 'every') : RULES));
        const every = [...document.querySelectorAll<HTMLElement>('[data-beast-grid] button, [data-beast-grid] [role="radio"]')].find((b) => b.textContent?.includes('beast.settings.trust_scope.option.every'));
        expect(every, 'the segmented choice for every folder').toBeDefined();
        every!.click();
        await vi.waitFor(() => expect(calls.some((c) => c.init?.method === 'PUT')).toBe(true));
        expect(JSON.parse(String(calls.find((c) => c.init?.method === 'PUT')!.init!.body))).toEqual({ trust_scope: 'every' });
    });
});

describe('beast mode grid model and registration', () => {
    test('the matrix has the two columns, the cells in order, and asks only for the unconfirmed rows', () => {
        const matrix = gridMatrix(RULES);
        expect(matrix.columns).toEqual(['beast.settings.column.off', 'beast.settings.column.on']);
        expect(matrix.rows[0]!.fields).toEqual(['devChannelsOff', 'devChannelsOn']);
        expect(matrix.rows.filter((r) => r.confirm).map((r) => Object.keys(r.confirm!)[0])).toEqual(['claudePermissionOff', 'codexApprovalOff', 'agentWritesOff']);
    });

    test('the scope form carries the server options and the narrow default', () => {
        const field = scopeSchema(RULES).fields[TRUST_SCOPE_KEY]!;
        expect(field.kind === 'enum' && field.options).toEqual(['projects', 'every']);
        expect(field.default).toBe('projects');
    });

    test('the grid is a setting in Advanced and the cross-session gate links to its tab', () => {
        const def = settingById('beast_grid')!;
        expect(def.section).toBe('advanced');
        expect(def.group).toBe('advanced.beast_mode');
        expect(groupOfSlug('advanced', 'beast_mode')).toBe('advanced.beast_mode');
        expect(BEAST_SETTINGS_HASH).toBe('#settings/advanced/beast_mode');
    });
});
