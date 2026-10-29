/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, tick, unmount } from 'svelte';

import BlueprintsScreen from './BlueprintsScreen.svelte';
import { createBlueprintsAdapter, familyTags, toBlueprintItem } from './blueprints-adapter';
import { blankSession, type Blueprint } from './types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { PSEUDO_LOCALE } from '../../../../client/js/i18n/pseudo.js';
import type { Translate } from '../sessions/types';

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);
const pseudo = createI18n({ locale: PSEUDO_LOCALE }) as { t: Translate };
const tPseudo: Translate = (key, params) => pseudo.t(key, params);

function blueprint(uuid: string, name: string, sessionCount = 1): Blueprint {
    const sessions = Array.from({ length: sessionCount }, (_, i) => blankSession(`agent ${i + 1}`));
    return {
        blueprint_uuid: uuid,
        name,
        spec: { version: 1, name, shape_template: null, sessions },
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    };
}

const BPS: Blueprint[] = [blueprint('bp-1', 'review team', 3), blueprint('bp-2', 'solo agent', 1)];

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) await Promise.resolve();
    await tick();
}

async function mountInto(props: Record<string, unknown>): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted = mount(BlueprintsScreen as never, { target, props: props as never });
    await settle();
    return target;
}

describe('the adapter', () => {
    test('list is GET /blueprints, mapped to items with a pluralised session count and no switch', async () => {
        let calls = 0;
        const fetcher = (async () => {
            calls += 1;
            return { status: 'ok', blueprints: BPS, detail: null };
        }) as never;
        const items = await createBlueprintsAdapter(t, fetcher).list();
        expect(calls).toBe(1);
        expect(items.map((i) => i.name)).toEqual(['review team', 'solo agent']);
        expect(items.map((i) => i.meta)).toEqual(['3 sessions', '1 session']);
        expect(items.every((i) => i.enabled === undefined)).toBe(true);
        expect(createBlueprintsAdapter(t, fetcher).setEnabled).toBeUndefined();
        expect(toBlueprintItem(BPS[0]!, t).blueprint).toBe(BPS[0]);
    });

    test('family tags cap at two with the rest folded into +n', () => {
        expect(familyTags([['claude', 2], ['codex', 1]])).toEqual(['claude 2', 'codex 1']);
        expect(familyTags([['claude', 2], ['codex', 1], ['shell', 1], ['unknown', 1]])).toEqual(['claude 2', 'codex 1', '+2']);
    });

    test('the item carries one tile family per distinct provider and per-family tags', () => {
        const mixed = blueprint('bp-3', 'mix', 0);
        mixed.spec.sessions = ['claude', 'claude', 'codex', 'shell', 'claude'].map((family, i) => ({ ...blankSession(`a${i}`), family }));
        const item = toBlueprintItem(mixed, t);
        expect(item.iconFamilies?.length).toBe(1);
        expect(item.tags).toEqual([`unknown 5`]);
        expect(item.byline).toBe('5 sessions');
    });

    test('an unavailable store rejects with the server sentence, never a silently empty list', async () => {
        const fetcher = (async () => ({ status: 'unavailable', blueprints: [], detail: 'the store could not be read' })) as never;
        await expect(createBlueprintsAdapter(t, fetcher).list()).rejects.toThrow('the store could not be read');
    });
});

describe('the page', () => {
    const adapter = { list: async () => BPS.map((bp) => toBlueprintItem(bp, t)) };

    test('lists every blueprint with a launch button, and draws no switch', async () => {
        const root = await mountInto({ adapter, t, embedded: true });
        const names = Array.from(root.querySelectorAll('.mgr-card__name')).map((el) => el.textContent?.trim());
        expect(names).toEqual(['review team', 'solo agent']);
        expect(root.querySelector('.oc-titlebar__title')?.textContent?.trim()).toBe('blueprints');
        expect(root.querySelectorAll('[data-blueprint-launch]').length).toBe(2);
        expect(root.querySelector('[role="switch"]')).toBeNull();
        expect(root.querySelector('[data-blueprint-new-open]')).not.toBeNull();
        expect(root.querySelector('[data-blueprint-import-open]')).not.toBeNull();
    });

    test('a card draws its marks in one tile (three at most), tags and the count in the footer', async () => {
        const root = await mountInto({ adapter, t, embedded: true });
        for (const card of root.querySelectorAll('.mgr-card--rich')) {
            expect(card.querySelectorAll('.oc-icon-tile--marks [role="img"]').length).toBeLessThanOrEqual(3);
            expect(card.querySelectorAll('.oc-icon-tile--marks [role="img"]').length).toBeGreaterThanOrEqual(1);
            expect(card.querySelectorAll('.mgr-card__foot .mgr-mark').length).toBeGreaterThanOrEqual(1);
            expect(card.querySelector('.mgr-card__foot .mgr-card__byline')?.textContent).toMatch(/sessions?$/);
            expect(card.querySelector('.mgr-card__meta')).toBeNull();
        }
    });

    test('the detail pane, not a kebab, carries edit, export and remove', async () => {
        const root = await mountInto({ adapter, t, embedded: true });
        (root.querySelector('.mgr-card__open') as HTMLButtonElement).click();
        await settle();
        expect(root.querySelector('[data-blueprint-edit]')).not.toBeNull();
        expect(root.querySelector('[data-blueprint-export]')).not.toBeNull();
        expect(root.querySelector('[data-blueprint-remove]')).not.toBeNull();
        expect(root.querySelectorAll('[data-blueprint-launch]').length).toBe(2);
    });

    test('an empty list uses the blueprint-specific sentence', async () => {
        const empty = { list: async () => [] };
        const root = await mountInto({ adapter: empty, t, embedded: true });
        expect(root.textContent).toContain(t('blueprint.empty'));
    });

    test('every page word comes from the catalog', async () => {
        const pAdapter = { list: async () => BPS.map((bp) => toBlueprintItem(bp, tPseudo)) };
        const root = await mountInto({ adapter: pAdapter, t: tPseudo, embedded: true });
        expect(root.querySelector('.oc-titlebar__title')?.textContent).toBe(tPseudo('blueprint.title'));
        expect(root.querySelector('[data-blueprint-new-open]')?.textContent).toBe(tPseudo('blueprint.new'));
    });
});
