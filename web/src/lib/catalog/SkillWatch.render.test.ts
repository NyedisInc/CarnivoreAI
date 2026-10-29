/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { mount, unmount } from 'svelte';

import AutopsyFacts from './AutopsyFacts.svelte';
import DetailActions from './DetailActions.svelte';
import type { CatalogHost } from './catalog';
import type { InstalledItem, SkillAutopsy } from './types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

let mounted: Record<string, unknown> | null = null;
const flush = () => new Promise((resolve) => setTimeout(resolve, 0));

async function paint(component: never, props: Record<string, unknown>): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    mounted = mount(component, { target, props: { t, ...props } as never }) as never;
    await flush();
}

afterEach(() => {
    if (mounted) unmount(mounted as never);
    mounted = null;
    document.body.innerHTML = '';
});

const MEASURED: SkillAutopsy = {
    skill: 'deploy', days: 30, state: 'measured', fires: 4, spans_measured: 4, tool_calls: 12,
    tool_errors: 2, interrupts: 1, corrections: 1, corrections_measured: 3, tokens_total: null,
    categories: { network: 2 }, undisclosed: ['network'],
    recent: [{ fired_at: '2026-09-28T10:00:00Z', session: 's1', tool_calls: 3, tool_errors: 1,
        interrupted: true, correction: true, next_excerpt: 'no, not that', ended: 'human' }],
};
const hostWith = (answer: unknown) => ({ skillAutopsy: async () => answer }) as unknown as CatalogHost;

describe('autopsy section', () => {
    test('measured counts, undisclosed categories and a redacted excerpt are printed', async () => {
        await paint(AutopsyFacts as never, { skill: 'deploy', host: hostWith(MEASURED) });
        const text = document.body.textContent ?? '';
        expect(text).toContain('4 runs read: 12 tool calls, 2 tool errors, 1 interrupts, 1 of 3 followed by a correction');
        expect(text).toContain('tokens: not recorded');
        expect(text).toContain('not disclosed by its review or allowed tools: network');
        expect(text).toContain('next message: no, not that');
    });

    test('cannot judge, judged clean and judged dirty read as three different things', async () => {
        await paint(AutopsyFacts as never, { skill: 'deploy', host: hostWith({ ...MEASURED, undisclosed: null }) });
        let text = document.body.textContent ?? '';
        expect(text).toContain('not judged: no review or allowed tools to compare with');
        expect(text).not.toContain('every observed category is disclosed');
        expect(text).toContain('risk categories seen: network');
        expect(text).toContain('a heuristic');
        document.body.innerHTML = '';
        await paint(AutopsyFacts as never, { skill: 'deploy', host: hostWith({ ...MEASURED, undisclosed: [] }) });
        text = document.body.textContent ?? '';
        expect(text).toContain('judged: every observed category is disclosed');
        expect(text).not.toContain('not judged');
    });

    test('not measured, a failed read and a missing host method never print a count', async () => {
        await paint(AutopsyFacts as never, { skill: 'deploy', host: hostWith({ ...MEASURED, state: 'not_measured', spans_measured: null }) });
        expect(document.body.textContent).toContain('not measured on this computer yet');
        expect(document.body.textContent).not.toContain('runs read');
        document.body.innerHTML = '';
        await paint(AutopsyFacts as never, { skill: 'deploy', host: { skillAutopsy: async () => { throw new Error('x'); } } as unknown as CatalogHost });
        expect(document.body.textContent).toContain('not measured on this computer yet');
        document.body.innerHTML = '';
        await paint(AutopsyFacts as never, { skill: 'deploy', host: {} as CatalogHost });
        expect(document.body.textContent).toContain('not measured on this computer yet');
    });
});

const ROW = (over: Partial<InstalledItem>): InstalledItem => ({
    install_id: 'i1', item_id: 'alex/deploy', name: 'deploy', scope: 'global', revision: 2, version: '1.0.0',
    ...over,
});
const actions = (row: InstalledItem, host: Partial<CatalogHost>) =>
    paint(DetailActions as never, {
        card: { id: 'alex/deploy', headline: 'deploy' }, installed: row, rowState: { kind: 'installed' },
        host: host as CatalogHost, onInstall() {}, onLedgerChange() {},
    });

describe('drift readout and actions', () => {
    test('a drifted row names the changed file and offers restore, uninstall and keep as fork', async () => {
        await actions(ROW({ drift: { state: 'drifted', changed_files: ['SKILL.md'] } }),
            { restoreInstalled: async () => ROW({}), setFork: async () => ROW({}) });
        expect(document.body.textContent).toContain('edited since it was installed');
        expect(document.body.textContent).toContain('changed: SKILL.md');
        for (const act of ['restore', 'drift-uninstall', 'fork']) {
            expect(document.querySelector(`[data-act="${act}"]`), act).not.toBeNull();
        }
    });

    test('a missing folder offers uninstall and no restore', async () => {
        await actions(ROW({ drift: { state: 'missing' } }), { restoreInstalled: async () => ROW({}) });
        expect(document.querySelector('[data-act="restore"]')).toBeNull();
        expect(document.querySelector('[data-act="drift-uninstall"]')).not.toBeNull();
    });

    test('changed files not measured is said, never an empty list', async () => {
        await actions(ROW({ drift: { state: 'drifted', changed_files: null } }), {});
        expect(document.body.textContent).toContain('which files changed was not recorded');
    });

    test('a clean row shows the verdict and no restore; a fork can be cleared', async () => {
        await actions(ROW({ drift: { state: 'clean' } }), {});
        expect(document.body.textContent).toContain('matches what was installed');
        expect(document.querySelector('[data-act="restore"]')).toBeNull();
        expect(document.querySelector('[data-act="fork"]')).toBeNull();
        document.body.innerHTML = '';
        const calls: Array<[string, boolean]> = [];
        await actions(ROW({ drift: { state: 'clean' }, forked: true }),
            { setFork: async (id, forked) => { calls.push([id, forked]); return ROW({ forked }); } });
        expect(document.body.textContent).toContain('kept as your own fork');
        (document.querySelector('[data-act="fork"]') as HTMLButtonElement).click();
        await flush();
        expect(calls).toEqual([['i1', false]]);
    });

    test('a row with no drift answer prints no drift block at all', async () => {
        await actions(ROW({}), {});
        expect(document.querySelector('[data-acts="drift"]')).toBeNull();
    });
});
