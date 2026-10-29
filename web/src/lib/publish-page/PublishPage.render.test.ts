/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { mount, unmount, flushSync } from 'svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { itemMenuState } from '../item-menu/open.svelte';
import { createActions } from './actions';
import { parseMine } from './api';
import type { PageHost } from './host';
import { createPageStore } from './page-store.svelte';
import PublishPage from './PublishPage.svelte';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

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

function page(setup: (store: ReturnType<typeof createPageStore>) => void = () => {}) {
    const host = { catalogSession: never, account: never, mine: never, listSkills: never, limits: never, rules: never, facts: never, report: never } as unknown as PageHost;
    const navigate = vi.fn();
    const store = createPageStore({ host, navigate, t });
    const actions = createActions({ store, host, t });
    store.folders = [
        { location: 'skill:notes', kind: 'skill', name: 'notes', harness: 'claude', description: '' },
        { location: 'skill:todo', kind: 'skill', name: 'todo', harness: 'claude', description: '' },
    ];
    store.mine = parseMine({ submissions: [{ submission_id: 'ab12', status: 'pending', gate_state: 'gating', kind: 'skill', name: 'notes', created_at: '2026-10-05T00:00:00Z' }] });
    setup(store);
    const target = document.createElement('div');
    document.body.appendChild(target);
    app = mount(PublishPage, { target, props: { store, actions, t } as never }) as never;
    flushSync();
    return { store, target, navigate };
}
const marker = (name: string) => document.querySelector(`[data-pp="${name}"]`);

describe('the frame', () => {
    it('draws the strip, the tabs, the list and the key with exactly the four stages in order', () => {
        page();
        expect(marker('PublishPage')).not.toBeNull();
        expect(document.querySelector('.pp-strip')).not.toBeNull();
        expect(document.querySelectorAll('.d-tabs [role="tab"]').length).toBe(5);
        const entries = [...document.querySelectorAll('.d-key__i')].map((e) => e.textContent?.trim());
        expect(entries).toHaveLength(4);
        expect(entries[0]).toContain(t('publish.page.stage.submitted'));
        expect(entries[3]).toContain(t('publish.page.stage.rejected'));
    });

    it('holds no limits text in the strip', () => {
        page((s) => { s.limits = { per_day: 5, used_today: 2 } as never; });
        expect(document.querySelector('.pp-strip')?.textContent).not.toMatch(/\b5\b.*\bday|2 of 5/i);
    });

    it('each mode mounts its own view', () => {
        const { store } = page();
        store.select('skill:notes', null, 'skills');
        flushSync();
        expect(marker('ItemPanels')).not.toBeNull();
        store.openEvent('ab12:gates');
        flushSync();
        expect(marker('ChecksView')).not.toBeNull();
        expect(document.querySelector('.d-back')?.textContent).toContain('notes');
        store.openRules();
        flushSync();
        expect(marker('RulesView')).not.toBeNull();
        expect(marker('ChecksView')).toBeNull();
    });

    it('a tab click while the rules are open closes them', () => {
        const { store } = page();
        store.select('skill:notes', null, 'skills');
        store.openRules();
        flushSync();
        (document.querySelectorAll('.d-tabs [role="tab"]')[2] as HTMLElement).click();
        flushSync();
        expect(store.rulesOpen).toBe(false);
    });

    it('Escape closes the rules once and does nothing while a menu is open', () => {
        const { store } = page();
        store.select('skill:notes', null, 'skills');
        store.openRules();
        flushSync();
        itemMenuState.open = { } as never;
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(store.rulesOpen).toBe(true);
        itemMenuState.open = null as never;
        window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }));
        expect(store.rulesOpen).toBe(false);
    });

    it('Escape on the document closes the rules and claims the key, so the shell handler stands down (X5-2)', () => {
        const { store } = page();
        store.select('skill:notes', null, 'skills');
        store.openRules();
        flushSync();
        const shell = vi.fn();
        document.addEventListener('keydown', (e) => { if (!e.defaultPrevented) shell(); });
        const event = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
        document.body.dispatchEvent(event);
        expect(store.rulesOpen).toBe(false);
        expect(event.defaultPrevented).toBe(true);
        expect(shell).not.toHaveBeenCalled();
    });

    it('the narrow container rule gives each kind tab vertical padding and a phone target (X5-22)', () => {
        const css = readFileSync(resolve(__dirname, 'page.css'), 'utf8');
        const narrow = css.slice(css.indexOf('@container pp (max-width: 719px)'));
        expect(narrow).toMatch(/\.d-tabs \.oc-ptab \{[^}]*padding-block:[^}]*min-height: var\(--oc-tap/);
    });

    it('with no item at all the page opens on the rules, once, and their back control returns to the list', () => {
        const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
        Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 1000 });
        try {
            const { store } = page((s) => { s.folders = []; s.mine = parseMine({ submissions: [] }); });
            flushSync();
            expect(store.rulesOpen).toBe(true);
            expect(marker('RulesView')).not.toBeNull();
            store.closeRules();
            flushSync();
            expect(store.rulesOpen).toBe(false);
            expect(store.view).toBe('list');
        } finally {
            if (width) Object.defineProperty(HTMLElement.prototype, 'clientWidth', width);
            else delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
        }
    });

    it('a row click selects the item and shows the dossier view', () => {
        const { store } = page();
        const row = document.querySelector('.d-row') as HTMLElement;
        row.click();
        flushSync();
        expect(store.sel).not.toBeNull();
        expect(store.view).toBe('dossier');
    });

    it('a failing source draws its own sentence and a retry, never blank', () => {
        page((s) => {
            s.mine = null;
            s.failure.mine = 'could not read your submissions: offline';
            s.failure.folders = 'could not read your folders: offline';
        });
        const text = document.querySelector('.d-list')?.textContent ?? '';
        expect(text).toContain('could not read your submissions: offline');
        expect(text).toContain('could not read your folders: offline');
        expect(document.querySelectorAll('.d-empty--fail button').length).toBeGreaterThan(0);
    });
});

function bare(report = vi.fn(async () => ({}))) {
    const host = { catalogSession: never, account: never, mine: never, listSkills: never, limits: never, rules: never, facts: never, report } as unknown as PageHost;
    const store = createPageStore({ host, navigate: vi.fn(), t });
    const actions = createActions({ store, host, t });
    return { store, host, actions, report };
}
const sub = (id: string, gate_state: string) => ({ submission_id: id, status: 'pending', gate_state, kind: 'skill', name: 'notes', created_at: '2026-10-05T00:00:00Z' });

describe('X6 fixes', () => {
    it('a received row and a gating row ask for no report on open or openEvent; a done row does (X6-5)', async () => {
        const { store, report } = bare();
        store.mine = parseMine({ submissions: [sub('rcv1', 'received'), sub('gat1', 'gating'), sub('don1', 'done')] });
        store.sel = 'skill:notes';
        await store.loadReport('rcv1');
        await store.loadReport('gat1');
        store.openEvent('rcv1:gates');
        store.openEvent('gat1:gates');
        expect(report).not.toHaveBeenCalled();
        store.openEvent('don1:gates');
        await store.loadReport('don1');
        expect(report).toHaveBeenCalledWith('don1');
    });

    it.each([['', 'an empty digest'], ['dg1', 'the refused digest']])('after a folder_changed refusal the list row phase is not checked, with %s (X6-19)', async (digest) => {
        const send = vi.fn(async () => { throw { detail: { code: 'folder_changed' } }; });
        const host = { send } as unknown as PageHost;
        const store = createPageStore({ host, navigate: vi.fn(), t });
        const actions = createActions({ store, host, t, now: () => new Date('2026-10-06T00:00:00Z') });
        store.folders = [{ location: 'skill:notes', kind: 'skill', name: 'notes', harness: 'claude', description: '' }];
        store.mine = parseMine({ submissions: [] });
        store.facts['skill:notes'] = { location: 'skill:notes', declared_version: '1.0.0', changed_files: 0, changed_at: '', made_at: '', sends: [], checks: [{ version: '1.0.0', ok: true, at: '2026-10-05T00:00:00Z', summary: '', digest }] };
        expect(store.checkOf('skill:notes')?.ok).toBe(true);
        const result = await actions.send({ location: 'skill:notes', version: '1.0.0', digest: 'dg1' });
        expect(result.ok).toBe(false);
        expect(store.checkOf('skill:notes')).toBeNull();
        expect(store.storedSendable('skill:notes')).toBeNull();
    });

    it('the refresh wash class lands on the positioned .d-list, not .d-groups (X6-13)', () => {
        page();
        const list = document.querySelector('.d-list') as HTMLElement;
        const groups = document.querySelector('.d-groups') as HTMLElement;
        expect(list.classList.contains('pp-flash')).toBe(false);
        const src = readFileSync(resolve(__dirname, 'ListColumn.svelte'), 'utf8');
        expect(src).toMatch(/<aside class="d-list" class:pp-flash=\{flash\}/);
        expect(groups.classList.contains('pp-flash')).toBe(false);
    });

    it('the phone container rule drops the 680 floor of .d-wrap (X6-8)', () => {
        const css = readFileSync(resolve(__dirname, 'page.css'), 'utf8');
        const block = css.slice(css.indexOf('@container pp (max-width: 719px)'));
        expect(block).toMatch(/\.d-wrap \{[^}]*min-height: 0/);
    });

    it('the search clear control is a thin cyan x (X6-14)', () => {
        const css = readFileSync(resolve(__dirname, 'list.css'), 'utf8');
        const rule = css.slice(css.indexOf('::-webkit-search-cancel-button'));
        expect(rule).toContain('var(--oc-cyan)');
        expect(rule.slice(0, rule.indexOf('}'))).not.toMatch(/40%|60%|text-bright/);
    });

    it('a narrow list transition scrolls the document to its top, never the pane root into view (X6-9)', () => {
        const src = readFileSync(resolve(__dirname, 'PublishPage.svelte'), 'utf8');
        expect(src).not.toContain('scrollIntoView');
        const scrollTo = vi.fn();
        vi.stubGlobal('scrollTo', scrollTo);
        const width = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientWidth');
        Object.defineProperty(HTMLElement.prototype, 'clientWidth', { configurable: true, get: () => 400 });
        try {
            const { store } = page();
            store.select('skill:notes', null, 'skills');
            flushSync();
            scrollTo.mockClear();
            store.goList();
            flushSync();
            expect(scrollTo).toHaveBeenCalledWith(0, 0);
            scrollTo.mockClear();
            store.applyNode({ scope: 'publish', page: 'item', tab: 'skills', location: 'skill:notes' } as never);
            flushSync();
            store.applyNode({ scope: 'publish', page: 'tab', tab: 'skills' } as never);
            flushSync();
            expect(scrollTo).toHaveBeenCalledWith(0, 0);
        } finally {
            if (width) Object.defineProperty(HTMLElement.prototype, 'clientWidth', width);
            else delete (HTMLElement.prototype as unknown as Record<string, unknown>).clientWidth;
        }
    });

    it('mine and folders failing with one sentence draw one failure block with one try again (X6-54)', () => {
        page((s) => {
            s.mine = null;
            s.failure.mine = 'could not reach the catalog: offline';
            s.failure.folders = 'could not reach the catalog: offline';
        });
        const blocks = document.querySelectorAll('.d-list .d-empty--fail');
        expect(blocks).toHaveLength(1);
        expect(blocks[0]?.querySelectorAll('button')).toHaveLength(1);
    });

    it('the strip text owns its row when signed out or without a handle, not with one (X7-8)', () => {
        page((s) => { s.signedIn = false; });
        expect(document.querySelector('.d-strip__h')?.hasAttribute('data-own')).toBe(true);
        unmount(app as never); app = null; document.body.innerHTML = '';
        page((s) => { s.signedIn = true; s.account = { handle: null, handle_status: null } as never; });
        expect(document.querySelector('.d-strip__h')?.hasAttribute('data-own')).toBe(true);
        unmount(app as never); app = null; document.body.innerHTML = '';
        page((s) => { s.signedIn = true; s.account = { handle: 'acme', handle_status: 'confirmed' } as never; });
        expect(document.querySelector('.d-strip__h')?.hasAttribute('data-own')).toBe(false);
    });
});
