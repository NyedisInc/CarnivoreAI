import { describe, expect, it } from 'vitest';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { parseMine } from './api';
import type { PageHost } from './host';
import { createPageStore } from './page-store.svelte';
import { cardViewOf } from './side-data';
import { buildRecords } from './list-model';
import { draftsOf, type Draft } from './wizard-state.svelte';
import { cardOf, type CardInput } from './card-model';

void enCatalog;
const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);
const SHA = 'a'.repeat(64);
const base: CardInput = { drafting: false, draft: { url: null, own: false }, outcome: 'none', send: null, media: [], kind: 'skill' };

describe('a withdrawn image row (H8)', () => {
    it('is not drawn as waiting for review', () => {
        const media = [{ status: 'withdrawn', created_at: '2026-10-26T00:00:00Z' }] as unknown as CardInput['media'];
        const c = cardOf({ ...base, send: { hero: 'made' }, media }, t);
        expect(c.state).not.toBe('waiting');
    });
});

describe('an own image already sent', () => {
    it('draws the stored copy when the send record names one', () => {
        const c = cardOf({ ...base, send: { hero: 'yours', sha: SHA } }, t);
        expect(c).toMatchObject({ state: 'made', picture: 'sent', sha: SHA, url: null });
    });

    it('keeps the glyph for a send made before copies were kept', () => {
        expect(cardOf({ ...base, send: { hero: 'yours', sha: '' } }, t)).toMatchObject({ picture: 'glyph', sha: null });
        expect(cardOf({ ...base, send: { hero: 'yours' } }, t)).toMatchObject({ picture: 'glyph', sha: null });
    });

    it('keeps the seeded art for a made image whatever the record holds', () => {
        expect(cardOf({ ...base, send: { hero: 'made', sha: SHA } }, t)).toMatchObject({ picture: 'art', sha: null });
    });
});

describe('replace the image after a withdraw (X6-21)', () => {
    const view = (rows: Record<string, unknown>[], phase?: Draft['phase']) => {
        const host = {} as unknown as PageHost;
        const store = createPageStore({ host, navigate: () => undefined, t });
        store.folders = [{ location: 'skill:notes', kind: 'skill', name: 'notes', harness: 'claude', description: '' }];
        store.mine = parseMine({ submissions: rows });
        store.signedIn = true;
        store.sel = 'skill:notes';
        if (phase) draftsOf(store).patch('skill:notes', { phase });
        const rec = buildRecords({ mine: store.mine, folders: store.folders, sendsOf: () => [], checkOf: () => null }).find((r) => r.location === 'skill:notes');
        if (!rec) throw new Error('no record');
        return cardViewOf(store, rec, t);
    };
    const row = (over: Record<string, unknown>) => ({ submission_id: 'ab12', status: 'withdrawn', gate_state: '', kind: 'skill', name: 'notes', version: '1.0.0', created_at: '2026-10-05T00:00:00Z', ...over });

    it('is offered for an item whose only send is withdrawn', () => {
        expect(view([row({})]).replaceable).toBe(true);
    });

    it('is not offered for an item never sent', () => {
        expect(view([]).replaceable).toBe(false);
    });
});
