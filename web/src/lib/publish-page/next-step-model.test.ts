import { describe, expect, it } from 'vitest';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { bump, changedNote, defaultVersion, factLines, threeVersions, versionRows, withdrawnAfter } from './item-model';
import { buildRecords, type ItemRecord } from './list-model';
import { leadText, stepOf, waitLeadKey, waitState, type Step, type StepInput } from './next-step-model';
import { canWithdraw } from './stages';
import type { Facts, SubRow } from './types';

const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

function row(over: Partial<SubRow> = {}): SubRow {
    return {
        id: 'ab12', status: 'pending', gate_state: 'received', item_id: 'item1', kind: 'skill', name: 'notes', version: '1.0.0', new_version: true,
        media_only: false, reason: '', appeals_left: null, created_at: '2026-10-05T10:00:00Z', decided_at: '', published_at: '', revoked_at: '',
        revocation_reason: '', events: [], ...over,
    };
}
const base: StepInput = { latest: null, withdrawn: null, phase: 'none', force: false };
const at = (over: Partial<StepInput>): Step => stepOf({ ...base, ...over });
const record = (over: Partial<ItemRecord> = {}): ItemRecord => ({
    location: 'skill:notes', folder: { location: 'skill:notes', kind: 'skill', name: 'notes', harness: 'claude', description: '' }, kind: 'skill', tab: 'skills',
    name: 'notes', harness: 'claude', subs: [], latest: null, phase: 'none', waits: false, ...over,
});

describe('the step of every state', () => {
    it('a draft starts step 1 and a checked one goes to send', () => {
        expect(at({})).toEqual({ kind: 'check', why: 'new', sub: null });
        expect(at({ phase: 'checked' })).toEqual({ kind: 'send' });
    });

    it('a refused local check is a fix list', () => {
        expect(at({ phase: 'refused' })).toMatchObject({ kind: 'fix', local: true });
    });

    it('an open row waits, in three ways for a row in review, and a check made after the send is still the wizard', () => {
        expect(at({ latest: row({ gate_state: 'received' }) })).toMatchObject({ kind: 'wait', state: 'submitted' });
        expect(at({ latest: row({ gate_state: 'gating' }) })).toMatchObject({ kind: 'wait', state: 'running' });
        expect(at({ latest: row({ gate_state: 'awaiting_approval' }) })).toMatchObject({ kind: 'wait', state: 'in_review' });
        expect(at({ latest: row({ gate_state: 'stuck' }) })).toMatchObject({ kind: 'wait', state: 'stuck' });
        expect(at({ latest: row({ status: 'publishing', gate_state: '' }) })).toMatchObject({ kind: 'wait', state: 'publishing' });
        expect(at({ latest: row({ status: 'approved', gate_state: '' }) })).toMatchObject({ kind: 'wait', state: 'approved' });
        expect(at({ latest: row({ gate_state: 'gating' }), phase: 'checked' })).toEqual({ kind: 'send' });
    });

    it('every wait state has a lead sentence key that exists', () => {
        for (const s of ['submitted', 'running', 'in_review', 'approved', 'stuck', 'publishing'] as const) {
            expect(t(waitLeadKey(s))).not.toBe(waitLeadKey(s));
        }
        expect(waitState({ status: 'pending', gate_state: '' })).toBe('in_review');
    });

    it('a failed gate is a fix list for that row', () => {
        expect(at({ latest: row({ status: 'gate_failed', gate_state: 'failed' }) })).toMatchObject({ kind: 'fix', local: false });
    });

    it('a rejection with 2, 1 or 0 appeals left', () => {
        for (const left of [2, 1]) expect(at({ latest: row({ status: 'rejected', appeals_left: left, reason: 'too thin' }) })).toMatchObject({ kind: 'appeal', left });
        expect(at({ latest: row({ status: 'rejected', appeals_left: 0, reason: 'too thin' }) })).toMatchObject({ kind: 'check', why: 'no_appeal' });
        expect(at({ latest: row({ status: 'rejected', appeals_left: null }) })).toMatchObject({ kind: 'check', why: 'no_appeal' });
    });

    it('a pulled, a withdrawn and a live item', () => {
        expect(at({ latest: row({ status: 'revoked' }) })).toMatchObject({ kind: 'check', why: 'revoked' });
        expect(at({ withdrawn: row({ status: 'withdrawn' }) })).toMatchObject({ kind: 'check', why: 'withdrawn' });
        expect(at({ latest: row({ status: 'published' }) })).toMatchObject({ kind: 'live' });
        expect(at({ latest: row({ status: 'published' }), force: true })).toMatchObject({ kind: 'check', why: 'again' });
        expect(at({ latest: row({ status: 'rejected', appeals_left: 2 }), force: true })).toMatchObject({ kind: 'check', why: 'again' });
        expect(at({ latest: row({ gate_state: 'gating' }), force: true })).toMatchObject({ kind: 'wait' });
    });

    it('the lead sentences of the wizard come from the catalog with their values', () => {
        expect(leadText(at({ withdrawn: row({ status: 'withdrawn', version: '1.2.0' }) }), '', t)).toBe('you withdrew 1.2.0. send it again whenever you like.');
        expect(leadText(at({ latest: row({ status: 'revoked', revocation_reason: 'copied work' }) }), '', t)).toBe('rejected: pulled from the store: copied work. fix what they named, raise the version and check it.');
        expect(leadText(at({ latest: row({ status: 'rejected', appeals_left: 0, reason: 'too thin' }) }), '', t)).toContain('no appeals left');
        expect(leadText({ kind: 'send' }, '1.1.0', t)).toBe('checked 1.1.0 and it can go. nothing was sent.');
        expect(leadText(at({}), '', t)).toBe('');
    });
});

describe('withdraw is offered exactly on pending and approved', () => {
    const cases: [string, string, boolean][] = [
        ['pending', 'gating', true], ['pending', 'received', true], ['approved', '', true], ['publishing', '', false],
        ['published', '', false], ['rejected', '', false], ['gate_failed', 'failed', false], ['withdrawn', '', false],
    ];
    it.each(cases)('status %s (%s): %s', (status, gate, offered) => {
        const sub = row({ status, gate_state: gate });
        expect(canWithdraw(sub)).toBe(offered);
        const step = at({ latest: sub });
        if (step.kind === 'wait') expect(step.withdraw).toBe(offered);
        else expect(offered).toBe(false);
    });
});

describe('the item header', () => {
    it('shows the three versions, with none and never as empty', () => {
        const live = row({ id: 'a', status: 'published', version: '1.0.0', created_at: '2026-09-01T00:00:00Z' });
        const open = row({ id: 'b', status: 'pending', version: '1.1.0', created_at: '2026-10-01T00:00:00Z' });
        const rec = record({ subs: [live, open], latest: open });
        const rows = versionRows(rec, [live, open, row({ id: 'w', status: 'withdrawn', version: '9.9.9' })]);
        expect(rows.map((r) => r.version)).toEqual(['1.1.0', '1.0.0']);
        expect(threeVersions(rows, '1.2.0')).toEqual({ approved: '1.0.0', sent: '1.1.0', onComputer: '1.2.0' });
        expect(threeVersions([], '')).toEqual({ approved: '', sent: '', onComputer: '' });
    });

    it('a replaced version stays under versions sent and a withdrawn one does not', () => {
        const old = row({ id: 'o', status: 'superseded', version: '1.0.0', created_at: '2026-09-01T00:00:00Z' });
        const live = row({ id: 'n', status: 'published', version: '1.1.0', created_at: '2026-10-01T00:00:00Z' });
        const rec = record({ subs: [live], latest: live });
        expect(versionRows(rec, [old, live]).map((r) => r.id)).toEqual(['n', 'o']);
    });

    it('the version a send starts with follows the declared version (D11)', () => {
        expect(defaultVersion('1.2.0', '1.1.0')).toBe('1.2.0');
        expect(defaultVersion('1.1.0', '1.1.0')).toBe('1.1.1');
        expect(defaultVersion('1.0.0', '1.1.0')).toBe('1.1.1');
        expect(defaultVersion('', '')).toBe('1.0.0');
        expect(defaultVersion('', '2.0.9')).toBe('2.0.10');
        expect(bump('1.9.9')).toBe('1.9.10');
    });

    it('the folder-changed note appears only when the folder differs from what was sent', () => {
        const sent = row({ version: '1.0.0' });
        const rec = record({ subs: [sent], latest: sent });
        const facts = (over: Partial<Facts>): Facts => ({ location: 'skill:notes', declared_version: '', changed_files: 0, changed_at: '', made_at: '', sends: [], checks: [], ...over });
        const now = Date.parse('2026-10-24T15:30:00Z');
        expect(changedNote(rec, facts({}), now)).toBeNull();
        expect(changedNote(record(), facts({ changed_files: 2, changed_at: '2026-10-24T12:00:00Z' }), now)).toBeNull();
        expect(changedNote(rec, undefined, now)).toBeNull();
        expect(changedNote(rec, facts({ changed_files: 2, changed_at: '2026-10-24T12:00:00Z' }), now)).toEqual({ version: '1.0.0', count: 2, hours: 3.5 });
    });

    it('a withdrawn row newer than the live ones is found by its send record, its item or a unique name', () => {
        const live = row({ id: 'l', status: 'published', created_at: '2026-09-01T00:00:00Z' });
        const gone = row({ id: 'g', status: 'withdrawn', version: '1.1.0', item_id: 'item9', created_at: '2026-10-01T00:00:00Z' });
        const rec = record({ subs: [live], latest: live });
        expect(withdrawnAfter(rec, [live, gone], ['g'], true)?.id).toBe('g');
        expect(withdrawnAfter(rec, [live, gone], [], false)?.id).toBe('g');
        expect(withdrawnAfter(rec, [live, gone], [], true)).toBeNull();
        const older = row({ id: 'g2', status: 'withdrawn', created_at: '2026-08-01T00:00:00Z' });
        expect(withdrawnAfter(rec, [live, older], ['g2'], false)).toBeNull();
    });

    it('a stored check older than a withdrawn send reads phase none, so the step is the withdrawn lead (X5-3)', () => {
        const folder = { location: 'skill:notes', kind: 'skill', name: 'notes', harness: 'claude', description: '' };
        const gone = row({ id: 'g', status: 'withdrawn', version: '1.0.0', created_at: '2026-10-05T10:00:00Z' });
        const join = (checkAt: string): ItemRecord => buildRecords({ mine: [gone], folders: [folder], sendsOf: () => ['g'], checkOf: () => ({ ok: true, at: checkAt }) })[0] as ItemRecord;
        const old = join('2026-10-05T09:00:00Z');
        expect(old.phase).toBe('none');
        const step = at({ latest: old.latest, withdrawn: withdrawnAfter(old, [gone], ['g'], false), phase: old.phase });
        expect(step).toMatchObject({ kind: 'check', why: 'withdrawn' });
        expect(join('2026-10-06T09:00:00Z').phase).toBe('checked');
    });

    it('the facts lines leave out what the app does not know', () => {
        const rec = record();
        const lines = factLines(rec, undefined, t).map((l) => l.label);
        expect(lines).toEqual(['kind', 'works with', 'read from']);
        const full = factLines(rec, { location: 'skill:notes', declared_version: '1.0.0', changed_files: 0, changed_at: '', made_at: '2026-10-01T09:00:00Z', sends: [], checks: [], kind: 'skill', name: 'notes', harness: 'claude', file_count: 2, total_bytes: 12345, files: [], license_file: true, license: 'MIT', grade: 'B', description_tokens_est: 12 } as Facts, t);
        expect(full.find((l) => l.label === 'files')?.value).toBe('2 files, 12,345 bytes');
        expect(full.find((l) => l.label === 'grade')?.value).toBe('B, good, with a few things to tidy');
        expect(full.find((l) => l.label === 'made here')?.value).toBe('1 oct');
    });
});
