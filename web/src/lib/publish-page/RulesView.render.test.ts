/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { createActions } from './actions';
import { parseLimits, parseRules } from './api-author';
import { parseMine } from './api';
import type { PageHost } from './host';
import { createPageStore } from './page-store.svelte';
import PublishPage from './PublishPage.svelte';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);
const golden = (name: string): unknown => JSON.parse(readFileSync(resolve(process.cwd(), `../tests/fixtures/publish_page/${name}.json`), 'utf8'));

class FakeObserver { observe(): void {} unobserve(): void {} disconnect(): void {} }
vi.stubGlobal('ResizeObserver', FakeObserver);

let app: Record<string, unknown> | null = null;
afterEach(() => {
    vi.stubGlobal('ResizeObserver', FakeObserver);
    if (app) unmount(app as never);
    app = null;
    document.body.innerHTML = '';
    globalThis.location.hash = '';
});

const never = () => new Promise<never>(() => {});

function page(folders: boolean, setup: (store: ReturnType<typeof createPageStore>) => void = () => {}) {
    const host = { catalogSession: never, account: never, mine: never, listSkills: never, limits: never, rules: never, facts: never, report: never } as unknown as PageHost;
    const store = createPageStore({ host, navigate: vi.fn(), t });
    const actions = createActions({ store, host, t });
    store.folders = folders ? [{ location: 'skill:notes', kind: 'skill', name: 'notes', harness: 'claude', description: '' }] : [];
    store.mine = parseMine({ submissions: folders ? [{ submission_id: 'ab12', status: 'pending', gate_state: 'gating', kind: 'skill', name: 'notes', created_at: '2026-10-05T00:00:00Z' }] : [] });
    store.limits = parseLimits(golden('limits'));
    store.rules = parseRules(golden('rules'));
    setup(store);
    const target = document.createElement('div');
    document.body.appendChild(target);
    app = mount(PublishPage, { target, props: { store, actions, t } as never }) as never;
    flushSync();
    return store;
}
const marker = (name: string) => document.querySelector(`[data-pp="${name}"]`);
const closes = (): HTMLButtonElement[] => [...document.querySelectorAll<HTMLButtonElement>('[data-pp="RulesView"] button')].filter((b) => b.textContent?.includes(t('publish.page.rules.close')));

function rulesOverStep() {
    const store = page(true);
    store.select('skill:notes', null, 'skills');
    store.openEvent('ab12:gates');
    flushSync();
    const held = store.mid;
    const view = store.view;
    expect(held).not.toBeNull();
    expect(view).toBe('dossier');
    store.openRules();
    flushSync();
    expect(marker('RulesView')).not.toBeNull();
    return { store, held, view };
}

describe('the rules view', () => {
    it('draws its panels from the loaded answers', () => {
        page(true, (s) => { s.openRules(); });
        const text = marker('RulesView')?.textContent ?? '';
        expect(text).toContain(t('publish.page.rules.title'));
        expect(text).toContain('2 of 5 today, 3 of 3 open');
        expect(text).toContain('5 images a day');
        expect(document.getElementById('d-rules-limits')).not.toBeNull();
    });

    it('the top close returns to the opened step held in from', () => {
        const { store, held, view } = rulesOverStep();
        closes()[0]?.click();
        flushSync();
        expect(store.rulesOpen).toBe(false);
        expect(store.mid).toEqual(held);
        expect(store.view).toBe(view);
        expect(marker('RulesView')).toBeNull();
    });

    it('the foot close returns to the opened step held in from', () => {
        const { store, held, view } = rulesOverStep();
        const all = closes();
        expect(all).toHaveLength(2);
        all[1]?.click();
        flushSync();
        expect(store.rulesOpen).toBe(false);
        expect(store.mid).toEqual(held);
        expect(store.view).toBe(view);
    });

    it('the back arrow returns to the opened step held in from', () => {
        const { store, held, view } = rulesOverStep();
        document.querySelector<HTMLButtonElement>(`[aria-label="${t('publish.page.strip.back_aria')}"]`)?.click();
        flushSync();
        expect(store.rulesOpen).toBe(false);
        expect(store.mid).toEqual(held);
        expect(store.view).toBe(view);
    });

    it('a failing limits read shows its sentence, and a closed kind shows the closed sentence', () => {
        page(true, (s) => {
            s.failure.limits = t('publish.page.failure.limits', { reason: 'offline' });
            const body = golden('rules') as { kinds: { kind: string; open: boolean }[] };
            s.rules = parseRules({ ...body, kinds: body.kinds.map((k) => (k.kind === 'themes' ? { ...k, open: false } : k)) });
            s.openRules();
        });
        const text = marker('RulesView')?.textContent ?? '';
        expect(text).toContain(t('publish.page.failure.limits', { reason: 'offline' }));
        expect(text).toContain(t('publish.page.kinds.closed', { kind: t('publish.page.tab.themes') }));
    });
});

describe('the empty page', () => {
    it('shows when no folder of any kind is found', () => {
        page(false);
        const el = marker('EmptyPage');
        expect(el).not.toBeNull();
        expect(el?.textContent).toContain(t('publish.page.empty.title'));
        expect(el?.textContent).toContain(t('publish.page.folder.plugin'));
    });
    it('is not drawn while an item is open', () => {
        page(true, (s) => s.select('skill:notes', null, 'skills'));
        expect(marker('EmptyPage')).toBeNull();
    });
});
