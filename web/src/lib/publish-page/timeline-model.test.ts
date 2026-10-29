import { describe, expect, it } from 'vitest';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { SubmissionReport } from '../catalog/publish';
import { cardOf, type CardInput } from './card-model';
import { GATE_IDS } from './report-format';
import { buildTimeline, FOLD_AFTER, type TimelineInput, type TlEntry, type TlItem } from './timeline-model';
import type { SubEvent, SubRow } from './types';

void enCatalog;
const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

const day = (n: number, h = 10): string => `2026-10-${String(n).padStart(2, '0')}T${String(h).padStart(2, '0')}:00:00Z`;
const ev = (what: string, at: string, extra: Partial<SubEvent> = {}): SubEvent => ({ at, what, ...extra });
const row = (id: string, over: Partial<SubRow> = {}): SubRow => ({
    id, status: 'pending', gate_state: 'received', item_id: 'bob/notes', kind: 'skill', name: 'notes', version: '1.0.0', new_version: true, media_only: false,
    reason: '', appeals_left: null, created_at: day(20), decided_at: '', published_at: '', revoked_at: '', revocation_reason: '', events: [], ...over,
});
const input = (over: Partial<TimelineInput> = {}): TimelineInput => ({
    name: 'notes', kind: 'skill', folderKey: 'publish.page.folder.skill', rows: [], media: [], sends: [], checks: [], madeAt: '', fileCount: 0, reports: {}, heroOutcome: 'none', ...over,
});
const entries = (items: TlItem[]): TlEntry[] => items.filter((i): i is TlEntry => i.kind === 'entry');
const titles = (items: TlItem[]): string[] => entries(items).map((e) => e.title);
const gateReport = (failIds: string[] = [], over: Record<string, { verdict: string; code: string }> = {}): SubmissionReport => ({
    outcome: failIds.length ? 'fail' : 'pass',
    gates: GATE_IDS.map((id) => ({ id, verdict: over[id]?.verdict ?? (failIds.includes(id) ? 'fail' : 'pass'), code: over[id]?.code ?? '', fix: '', findings: [] })),
});

describe('the timeline from real times only', () => {
    it('builds the steps of a row from its events, oldest first, with the mockup titles', () => {
        const r = row('a', {
            status: 'rejected', gate_state: 'awaiting_approval', appeals_left: 2,
            events: [ev('received', day(20)), ev('gating', day(20, 11)), ev('awaiting_approval', day(20, 12), { text: 'passed' }), ev('rejected', day(21), { reason: 'no license' })],
        });
        const out = buildTimeline(input({ rows: [r], reports: { a: gateReport() } }), t);
        expect(titles(out)).toEqual(['submitted', 'the 12 checks', 'in review', 'rejected: no license']);
        expect(entries(out)[3]?.meta).toBe('2 appeals left');
        expect(entries(out)[1]?.meta).toBe('12 of 12 passed');
    });

    it('gives folder made and checked {v}, clean from the local records, and a refused check its step with no send', () => {
        const out = buildTimeline(input({
            madeAt: day(18), fileCount: 3,
            checks: [{ version: '1.0.1', ok: false, at: day(19), summary: 'secret_found, license_missing' }, { version: '1.0.0', ok: true, at: day(18, 12), summary: 'clean' }],
        }), t);
        expect(titles(out)).toEqual(['folder made', 'checked 1.0.0, clean', 'checked 1.0.1, did not pass: secret_found, license_missing']);
        expect(entries(out)[0]?.meta).toBe('3 files in your skills folder');
        expect(titles(out).some((x) => x.startsWith('sent'))).toBe(false);
        expect(entries(out)[2]?.key).toMatch(/^chk0:/);
        expect(entries(out)[2]?.open).toBe(true);
    });

    it('keeps the earlier rejection and its reason when an appeal was made', () => {
        const r = row('a', {
            status: 'pending', gate_state: 'awaiting_approval', appeals_left: 1,
            events: [ev('received', day(20)), ev('gating', day(20, 11)), ev('awaiting_approval', day(20, 12)), ev('rejected', day(21), { reason: 'no license' }), ev('appealed', day(22), { text: 'license added' })],
        });
        const out = buildTimeline(input({ rows: [r], reports: { a: gateReport() } }), t);
        expect(titles(out)).toEqual(['submitted', 'the 12 checks', 'in review', 'rejected: no license', 'appeal sent', 'in review again']);
        const rejected = entries(out).find((e) => e.title === 'rejected: no license');
        expect(rejected?.meta).toBe('appealed');
        expect(entries(out).find((e) => e.title === 'appeal sent')?.meta).toBe('license added');
        expect(entries(out).at(-1)?.meta).toBe('a person looks at your appeal next.');
    });

    it('a revoked row gives rejected: pulled from the store with the reason and what to do', () => {
        const r = row('a', { status: 'revoked', events: [ev('received', day(20)), ev('approved', day(21)), ev('published', day(21, 12)), ev('revoked', day(25), { reason: 'bad license' })] });
        const out = buildTimeline(input({ rows: [r] }), t);
        const last = entries(out).at(-1);
        expect(last?.title).toBe('rejected: pulled from the store: bad license');
        expect(last?.meta).toBe('what to do: fix what they named, raise the version and send it again.');
        expect(last?.mark).toEqual({ kind: 'stage', stage: 'rejected' });
    });

    it('a withdrawal gives you withdrew {v}; a superseded row gives version {v} took its place', () => {
        const w = row('w', { version: '1.0.0', status: 'withdrawn', events: [ev('received', day(20)), ev('withdrawn', day(21))] });
        const s = row('s', { version: '1.1.0', status: 'superseded', created_at: day(22), events: [ev('received', day(22)), ev('superseded', day(23), { version: '1.2.0' })] });
        const out = buildTimeline(input({ rows: [w, s] }), t);
        expect(titles(out)).toContain('you withdrew 1.0.0');
        expect(titles(out)).toContain('version 1.2.0 took its place');
    });

    it('a gate that failed counts its failures from the report, and says rejected until the report is loaded', () => {
        const r = row('a', { status: 'gate_failed', gate_state: 'awaiting_approval', events: [ev('received', day(20)), ev('gating', day(20, 11)), ev('gate_failed', day(20, 12), { text: 'failed' })] });
        const withReport = buildTimeline(input({ rows: [r], reports: { a: gateReport(['secrets', 'license']) } }), t);
        expect(titles(withReport)).toContain('rejected: 2 of 12 checks did not pass');
        const without = buildTimeline(input({ rows: [r] }), t);
        expect(titles(without)).toContain('rejected');
    });

    it('a run still on shows the running title and no count', () => {
        const r = row('a', { gate_state: 'gating', events: [ev('received', day(20)), ev('gating', day(20, 11))] });
        const out = buildTimeline(input({ rows: [r] }), t);
        expect(titles(out)).toEqual(['submitted', 'in review: the 12 checks are running']);
        expect(entries(out)[1]?.key).toBe('a:gates');
    });

    it('the clean room mention rides on a cplug report that skipped it', () => {
        const r = row('a', { kind: 'cplug', status: 'pending', gate_state: 'awaiting_approval', events: [ev('received', day(20)), ev('gating', day(20, 11)), ev('awaiting_approval', day(20, 12))] });
        const report = gateReport([], { clean_room: { verdict: 'advisory', code: 'skipped_by_policy' } });
        const out = buildTimeline(input({ kind: 'cplug', rows: [r], reports: { a: report } }), t);
        expect(entries(out)[1]?.meta).toBe('12 of 12 passed. clean room run: skipped by policy');
    });

    it('a row with no events shows only its stored stamps and invents none', () => {
        const r = row('a', { status: 'approved', gate_state: 'awaiting_approval', created_at: day(20), decided_at: day(21) });
        const out = buildTimeline(input({ rows: [r] }), t);
        expect(titles(out)).toEqual(['submitted', 'approved']);
        const open = buildTimeline(input({ rows: [row('b', { gate_state: 'gating' })] }), t);
        expect(titles(open)).toEqual(['submitted']);
    });

    it('folds past 16 events and 2 submissions, keeping the newest two versions open', () => {
        const rows = ['1.0.0', '1.1.0', '1.2.0', '1.3.0'].map((v, i) =>
            row(`r${i}`, { version: v, status: 'pending', gate_state: 'awaiting_approval', created_at: day(10 + i * 2), events: [ev('received', day(10 + i * 2)), ev('gating', day(10 + i * 2, 11)), ev('awaiting_approval', day(10 + i * 2, 12)), ev('rejected', day(11 + i * 2), { reason: 'x' }), ev('appealed', day(11 + i * 2, 12), { text: 'y' })]}),
        );
        const out = buildTimeline(input({ rows, reports: Object.fromEntries(rows.map((r) => [r.id, gateReport()])) }), t);
        expect(entries(buildTimeline(input({ rows: rows.slice(0, 2) }), t)).length).toBeLessThan(FOLD_AFTER + 1);
        const fold = out.find((i) => i.kind === 'fold');
        expect(fold?.kind === 'fold' && fold.summary).toBe('1.0.0 to 1.1.0, 12 events');
        expect(entries(out).every((e) => e.grp === 'r2' || e.grp === 'r3' || e.grp === 'head' || e.grp === 'tail')).toBe(true);
    });

    it('images: made and chosen come from the send record and its media row, a replaced one is image sent for review', () => {
        const r = row('a', { events: [ev('received', day(20))] });
        const media = [row('m1', { media_only: true, created_at: day(20, 10) }), row('m2', { media_only: true, created_at: day(22) })];
        const out = buildTimeline(input({ rows: [r], media, sends: [{ submission_id: 'a', version: '1.0.0', sent_at: day(20), hero: 'yours', media_submission_id: 'm2' }] }), t);
        expect(titles(out)).toContain('image: yours');
        expect(titles(out)).toContain('image sent for review');
        expect(titles(out)).toContain('sent 1.0.0');
        expect(entries(out).find((e) => e.title === 'sent 1.0.0')?.meta).toBe('image: yours. it waits for the checks.');
    });
});

describe('the card source line and picture, for each hero state', () => {
    const base: CardInput = { drafting: false, draft: { url: null, own: false }, outcome: 'none', send: null, media: [], kind: 'skill' };
    const state = (over: Partial<CardInput>): string => cardOf({ ...base, ...over }, t).state;
    const line = (over: Partial<CardInput>): string => cardOf({ ...base, ...over }, t).source;
    const media = (status: string, extra: Partial<SubRow> = {}): SubRow => row('m', { media_only: true, status, ...extra });

    it('chosen: an own image held for the send', () => {
        const c = cardOf({ ...base, drafting: true, draft: { url: 'blob:x', own: true } }, t);
        expect([c.state, c.source, c.picture, c.url]).toEqual(['chosen', 'yours, not sent yet', 'url', 'blob:x']);
    });
    it('none while drafting says we make one when you send; none after says no image yet', () => {
        expect(line({ drafting: true })).toBe('we make one for you when you send');
        expect(state({})).toBe('none');
        expect(line({})).toBe('no image yet');
    });
    it('being made: the glyph and making an image for you', () => {
        const c = cardOf({ ...base, outcome: 'making', send: { hero: 'made' } }, t);
        expect([c.state, c.source, c.picture]).toEqual(['making', 'making an image for you', 'glyph']);
    });
    it('could not make: the glyph and the hosted line', () => {
        const c = cardOf({ ...base, outcome: 'failed', send: { hero: 'made' } }, t);
        expect([c.state, c.picture]).toEqual(['failed', 'glyph']);
        expect(c.source).toBe('could not make an image. the card shows its glyph until you add one.');
    });
    it('made: a sent image with no media row to read yet draws the art for a made one', () => {
        const c = cardOf({ ...base, send: { hero: 'made' } }, t);
        expect([c.state, c.source, c.picture]).toEqual(['made', 'made for you', 'art']);
    });
    it('sent and waiting for review: a pending media row', () => {
        const c = cardOf({ ...base, send: { hero: 'made' }, media: [media('pending')] }, t);
        expect([c.state, c.source, c.picture]).toEqual(['waiting', 'image sent. it waits for review.', 'art']);
    });
    it('approved: the media row approved', () => {
        expect(cardOf({ ...base, send: { hero: 'made' }, media: [media('approved')] }, t).source).toBe('made for you');
        expect(cardOf({ ...base, send: { hero: 'yours' }, media: [media('published')] }, t)).toMatchObject({ state: 'approved', source: 'yours', picture: 'glyph' });
    });
    it('rejected: the glyph and the reason', () => {
        const c = cardOf({ ...base, send: { hero: 'yours' }, media: [media('rejected', { reason: 'too dark' })] }, t);
        expect([c.state, c.picture, c.source]).toEqual(['rejected', 'glyph', 'the image was rejected: too dark']);
    });
    it('the newest media row decides', () => {
        const old = media('rejected', { created_at: day(19), reason: 'x' });
        const fresh = media('pending', { created_at: day(22) });
        expect(state({ send: { hero: 'yours' }, media: [old, fresh] })).toBe('waiting');
    });
});

describe('a local check says what it read', () => {
    it('shows the grade, the file count and the bytes of a clean check, and nothing for a check that kept none', () => {
        const kept = { version: '1.0.0', ok: true, at: day(20), summary: 'clean', preview: { notes: 0, files: 14, bytes: 88210, grade: 'B' } };
        const bare = { version: '0.9.0', ok: true, at: day(19), summary: 'clean' };
        const out = entries(buildTimeline(input({ checks: [kept, bare] }), t));
        expect(out.find((e) => e.title.includes('1.0.0'))?.meta).toBe('grade B, 14 files, 88,210 bytes');
        expect(out.find((e) => e.title.includes('0.9.0'))?.meta).toBe('');
    });
});
