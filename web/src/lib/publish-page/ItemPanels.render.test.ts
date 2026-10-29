/** @vitest-environment jsdom */
import { afterEach, describe, expect, it, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { createActions } from './actions';
import { parseMine } from './api';
import type { PageHost } from './host';
import ItemPanels from './ItemPanels.svelte';
import LocalCheckView from './LocalCheckView.svelte';
import { createPageStore } from './page-store.svelte';
import type { CheckEntry, LocalCheck } from './types';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);
const EMPTY = t('publish.page.versions.empty');

let app: Record<string, unknown> | null = null;
afterEach(() => {
    if (app) unmount(app as never);
    app = null;
    document.body.innerHTML = '';
});

const row = { submission_id: 'ab12', status: 'rejected', gate_state: 'failed', kind: 'skill', name: 'notes', version: '1.0.0', created_at: '2026-10-05T00:00:00Z' };
const record = (over: Partial<LocalCheck> = {}): LocalCheck => ({ version: '1.0.0', ok: false, at: '2026-10-06T10:00:00Z', summary: 'secret_found, license_missing', ...over });

function mountView(view: typeof ItemPanels | typeof LocalCheckView, opts: { noRows?: boolean; factsFailed?: boolean; checks?: LocalCheck[]; live?: CheckEntry; ev?: string } = {}) {
    const fake = {} as unknown as PageHost;
    const store = createPageStore({ host: fake, navigate: vi.fn(), t });
    const actions = createActions({ store, host: fake, t });
    store.folders = [{ location: 'skill:notes', kind: 'skill', name: 'notes', harness: 'claude', description: '' }];
    store.mine = parseMine({ submissions: opts.noRows ? [] : [row] });
    store.signedIn = true;
    store.sel = 'skill:notes';
    if (opts.factsFailed) store.failure.facts = 'the details of this item could not be read';
    else store.facts['skill:notes'] = { location: 'skill:notes', declared_version: '1.0.0', changed_files: 0, changed_at: '', made_at: '', sends: [], checks: opts.checks ?? [] };
    if (opts.live) store.checks['skill:notes'] = opts.live;
    if (opts.ev) store.mid = { ev: opts.ev };
    const target = document.createElement('div');
    document.body.appendChild(target);
    app = mount(view, { target, props: { store, actions, t } as never }) as never;
    flushSync();
    return target;
}

const live = (over: Partial<CheckEntry> = {}): CheckEntry => ({
    version: '1.0.0',
    ok: false,
    at: '2026-10-06T10:00:00Z',
    summary: 'secret_found',
    preview: {
        location: 'skill:notes', name: 'notes', version: '1.0.0', file_count: 2, total_bytes: 1840, digest: 'd', can_send: false, cost: {}, compat: {},
        files: [{ path: 'SKILL.md', size: 900 }, { path: 'scripts/render.sh', size: 940 }],
        refusals: [{ code: 'secret_found', path: 'scripts/render.sh', detail: 'looks like a key' }],
        lint: { grade: 'B', failed: [{ rule: 'long_line', detail: 'line 4' }] },
    },
    ...over,
});

describe('the versions panel', () => {
    it('a failed facts read does not claim nothing was sent (X6-6)', () => {
        const target = mountView(ItemPanels, { noRows: true, factsFailed: true });
        expect(target.textContent).not.toContain(EMPTY);
    });

    it('a good read of an item with no sends still says so', () => {
        const target = mountView(ItemPanels, { noRows: true });
        expect(target.textContent).toContain(EMPTY);
    });
});

describe('the local check view', () => {
    it('the FILES fact holds "bytes" once, live and stored (X6-3)', () => {
        const liveView = mountView(LocalCheckView, { live: live({ ok: true, summary: '' }) });
        const cell = [...liveView.querySelectorAll('dl.d-facts > div')].find((d) => d.querySelector('dt')?.textContent === t('publish.page.fact.files'));
        expect(cell?.querySelector('dd')?.textContent).toBe('2 files, 1,840 bytes');
        unmount(app as never);
        document.body.innerHTML = '';
        const storedView = mountView(LocalCheckView, { checks: [record({ ok: true, summary: '', files: 14, bytes: 88210 })], ev: 'chk0:x' });
        const stored = [...storedView.querySelectorAll('dl.d-facts > div')].find((d) => d.querySelector('dt')?.textContent === t('publish.page.fact.files'));
        expect(stored?.querySelector('dd')?.textContent).toBe('14 files, 88,210 bytes');
    });

    it('the newest refused record with a same version live check draws the full view (X6-20)', () => {
        const target = mountView(LocalCheckView, { checks: [record()], live: live(), ev: 'chk0:x' });
        const text = target.textContent ?? '';
        expect(text).toContain('secret_found in scripts/render.sh');
        expect(text).toContain('looks like a key');
        expect(text).toContain(t('publish.page.local.notes'));
        expect(text).toContain(t('publish.page.local.files_read'));
    });

    it('a stored record with findings draws "code in path", a code with none stays a code', () => {
        const target = mountView(LocalCheckView, { checks: [record({ findings: [{ code: 'secret_found', path: 'scripts/render.sh' }] })], ev: 'chk0:x' });
        const items = [...target.querySelectorAll('ul.d-refuse li')].map((li) => li.textContent?.trim());
        expect(items).toEqual(['secret_found in scripts/render.sh', 'license_missing']);
    });

    it('a live refused preview without files, refusals or lint keys draws its heading, THIS CHECK and DID NOT PASS without throwing (X7-1)', () => {
        const short = live();
        const { files: _files, lint: _lint, ...bare } = short.preview as unknown as Record<string, unknown>;
        short.preview = { ...bare, refusals: [{ code: 'secret_found' }] } as never;
        const target = mountView(LocalCheckView, { checks: [record()], live: short, ev: 'chk0:x' });
        const text = target.textContent ?? '';
        expect(target.querySelector('h2')?.textContent).toContain('did not pass');
        expect(text).toContain(t('publish.page.local.this_check'));
        expect(text).toContain(t('publish.page.local.did_not_pass'));
        expect(text).not.toContain(t('publish.page.local.files_read'));
    });

    it('a live refused preview with files also draws THE FILES IT READ (X7-1)', () => {
        const target = mountView(LocalCheckView, { checks: [record()], live: live(), ev: 'chk0:x' });
        expect(target.textContent).toContain(t('publish.page.local.files_read'));
        expect(target.textContent).toContain('SKILL.md');
    });

    it('an older stored record, not the newest, never takes the live preview', () => {
        const target = mountView(LocalCheckView, { checks: [record({ version: '1.0.1' }), record()], live: live(), ev: 'chk1:x' });
        expect(target.textContent).not.toContain('looks like a key');
    });
});
