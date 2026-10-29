import { describe, expect, it } from 'vitest';
import enCatalog from '../../../../client/js/i18n/catalog.en.js';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { PublishableSkill } from '../catalog/publish';
import { buildRecords, kindList, submissionGroups, tabStats, type JoinInput } from './list-model';
import type { SubRow } from './types';

void enCatalog;
const i18n = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null): string => i18n.t(key, params);

function sub(id: string, over: Partial<SubRow> = {}): SubRow {
    return {
        id, status: 'pending', gate_state: 'received', item_id: `bob/${over.name ?? 'x'}`, kind: 'skill', name: 'x', version: '1.0.0', new_version: true, media_only: false,
        reason: '', appeals_left: null, created_at: '2026-10-20T10:00:00Z', decided_at: '', published_at: '', revoked_at: '', revocation_reason: '', events: [], ...over,
    };
}
const folder = (location: string, name: string, harness: string, kind?: string): PublishableSkill => ({ location, kind, name, harness, description: '' });

function input(mine: SubRow[], folders: PublishableSkill[], over: Partial<JoinInput> = {}): JoinInput {
    return { mine, folders, sendsOf: () => [], checkOf: () => null, ...over };
}

describe('a failed source is not a zero count (X5-5)', () => {
    it('a failed folder list leaves the kind tabs without a count, a failed hosted list leaves submissions without one', () => {
        const stats = tabStats([], { submissions: true, kinds: true });
        expect(stats.skills.count).toBeNull();
        expect(stats.submissions.count).toBeNull();
        expect(tabStats([], { submissions: false, kinds: false }).skills.count).toBe(0);
    });
});

describe('the join of hosted rows to folders (D10)', () => {
    const folders = [folder('skill:velridge-belford:claude', 'velridge-belford', 'claude'), folder('skill:velridge-belford:codex', 'velridge-belford', 'codex'), folder('skill:notes', 'notes', 'claude')];

    it('joins by the local send record first, then by the only folder of that kind and name', () => {
        const rows = [sub('a', { name: 'velridge-belford', status: 'approved' }), sub('b', { name: 'notes' })];
        const records = buildRecords(input(rows, folders, { sendsOf: (loc) => (loc === 'skill:velridge-belford:codex' ? ['a'] : []) }));
        const byLoc = Object.fromEntries(records.map((r) => [r.location, r.latest?.id ?? null]));
        expect(byLoc['skill:velridge-belford:codex']).toBe('a');
        expect(byLoc['skill:velridge-belford:claude']).toBeNull();
        expect(byLoc['skill:notes']).toBe('b');
    });

    it('a twin without a record joins neither folder and shows on its own, without a harness', () => {
        const records = buildRecords(input([sub('a', { name: 'velridge-belford' })], folders));
        expect(records.filter((r) => r.folder && r.latest)).toHaveLength(0);
        const orphan = records.find((r) => r.latest?.id === 'a');
        expect(orphan?.folder).toBeNull();
        expect(orphan?.harness).toBe('');
        expect(orphan?.location).toBe('item:bob/velridge-belford');
    });

    it('does not join a plugin row to a compiled in plugin folder of the same name', () => {
        const records = buildRecords(input([sub('a', { name: 'pulse', kind: 'plugin' })], [folder('cplug:pulse', 'pulse', '', 'cplug')]));
        expect(records.find((r) => r.location === 'cplug:pulse')?.latest).toBeNull();
    });

    it('one record per item at its newest version; withdrawn, superseded and media rows are not rows', () => {
        const rows = [
            sub('old', { name: 'notes', version: '1.0.0', status: 'superseded', created_at: '2026-10-01T00:00:00Z' }),
            sub('mid', { name: 'notes', version: '1.1.0', status: 'approved', created_at: '2026-10-05T00:00:00Z' }),
            sub('new', { name: 'notes', version: '1.2.0', status: 'withdrawn', created_at: '2026-10-09T00:00:00Z' }),
            sub('img', { name: 'notes', media_only: true, created_at: '2026-10-10T00:00:00Z' }),
        ];
        const record = buildRecords(input(rows, folders)).find((r) => r.location === 'skill:notes');
        expect(record?.latest?.id).toBe('mid');
        expect(record?.subs.map((s) => s.id)).toEqual(['mid']);
    });

    it('a check older than the newest send is stale; a newer one gives the phase', () => {
        const rows = [sub('a', { name: 'notes', status: 'approved', created_at: '2026-10-05T00:00:00Z' })];
        const stale = buildRecords(input(rows, folders, { checkOf: () => ({ ok: false, at: '2026-10-01T00:00:00Z' }) }));
        expect(stale.find((r) => r.location === 'skill:notes')?.phase).toBe('none');
        const fresh = buildRecords(input(rows, folders, { checkOf: () => ({ ok: false, at: '2026-10-06T00:00:00Z' }) }));
        expect(fresh.find((r) => r.location === 'skill:notes')?.phase).toBe('refused');
        const ok = buildRecords(input([], folders, { checkOf: () => ({ ok: true, at: '2026-10-06T00:00:00Z' }) }));
        expect(ok.find((r) => r.location === 'skill:notes')?.phase).toBe('checked');
    });
});

describe('your submissions: groups, rows, search', () => {
    const folders = [folder('skill:a', 'a', 'claude'), folder('skill:b', 'b', 'claude'), folder('skill:c', 'c', 'claude'), folder('skill:d', 'd', 'claude'), folder('skill:e', 'e', 'claude'), folder('skill:f', 'f', 'claude')];
    const rows = [
        sub('s1', { name: 'a', status: 'pending', gate_state: 'received', created_at: '2026-10-20T10:00:00Z' }),
        sub('s2', { name: 'b', status: 'pending', gate_state: 'gating', created_at: '2026-10-21T10:00:00Z' }),
        sub('s3', { name: 'c', status: 'published', gate_state: 'awaiting_approval', created_at: '2026-10-19T10:00:00Z' }),
        sub('s4', { name: 'd', status: 'rejected', appeals_left: 0, created_at: '2026-10-18T10:00:00Z' }),
        sub('s5', { name: 'e', status: 'gate_failed', created_at: '2026-10-17T10:00:00Z' }),
        sub('s6', { name: 'f', status: 'rejected', appeals_left: 2, created_at: '2026-10-22T10:00:00Z' }),
    ];
    const records = buildRecords(input(rows, folders));

    it('orders the groups needs you, submitted, in review, approved, rejected', () => {
        const groups = submissionGroups(records, '', t);
        expect(groups.map((g) => g.bucket)).toEqual(['needs_you', 'submitted', 'in_review', 'approved', 'rejected']);
        expect(groups[0]!.rows.map((r) => r.subId)).toEqual(['s6', 's5']);
        expect(groups[4]!.rows.map((r) => r.subId)).toEqual(['s4']);
    });

    it('a local check that did not pass moves its row to needs you', () => {
        const checked = buildRecords(input(rows, folders, { checkOf: (loc) => (loc === 'skill:a' ? { ok: false, at: '2026-10-25T00:00:00Z' } : null) }));
        const groups = submissionGroups(checked, '', t);
        expect(groups[0]!.rows.map((r) => r.subId)).toContain('s1');
        expect(groups.find((g) => g.bucket === 'submitted')).toBeUndefined();
    });

    it('a row on "your submissions" reads its bare stage word even when the local check did not pass; a kind tab reads the check word', () => {
        const checked = buildRecords(input(rows, folders, { checkOf: (loc) => (loc === 'skill:a' ? { ok: false, at: '2026-10-25T00:00:00Z' } : null) }));
        const row = submissionGroups(checked, '', t).flatMap((g) => g.rows).find((r) => r.subId === 's1');
        expect(row?.wordKey).toBe('publish.page.stage.submitted');
        expect(kindList(checked, 'skills', '').find((r) => r.name === 'a')?.wordKey).toBe('publish.page.row.check_failed');
    });

    it('searches name, version, stage word, kind and harness, and nothing else', () => {
        const ids = (q: string): string[] => submissionGroups(records, q, t).flatMap((g) => g.rows.map((r) => r.subId ?? ''));
        expect(ids('a')).toContain('s1');
        expect(ids('1.0.0').length).toBe(6);
        expect(ids('in review')).toEqual(['s2']);
        expect(ids('claude').length).toBe(6);
        expect(ids('skill').length).toBe(6);
        expect(ids('video')).toEqual([]);
    });

    it('a row carries the stage word key and its date', () => {
        const first = submissionGroups(records, '', t).find((g) => g.bucket === 'submitted')?.rows[0];
        expect(first?.wordKey).toBe('publish.page.stage.submitted');
        expect(first?.date).toBe('2026-10-20T10:00:00Z');
    });
});

describe('the kind tabs', () => {
    const folders = [folder('skill:zeta', 'zeta', 'claude'), folder('skill:alpha', 'alpha', 'codex'), folder('skill:mid', 'mid', 'claude'), folder('theme:neon', 'neon', '', 'theme'), folder('cplug:pulse', 'pulse', '', 'cplug'), folder('plugin:tool', 'tool', 'claude', 'plugin')];
    const rows = [sub('r1', { name: 'mid', status: 'rejected', appeals_left: 1 })];
    const records = buildRecords(input(rows, folders));

    it('lists waits on you first, then by name', () => {
        expect(kindList(records, 'skills', '').map((r) => r.name)).toEqual(['mid', 'alpha', 'zeta']);
    });

    it('the plugins tab holds both plugin kinds and keeps the real kind', () => {
        const list = kindList(records, 'plugins', '');
        expect(list.map((r) => r.name)).toEqual(['pulse', 'tool']);
        expect(list.map((r) => r.kind)).toEqual(['cplug', 'plugin']);
    });

    it('searches only name and harness', () => {
        expect(kindList(records, 'skills', 'codex').map((r) => r.name)).toEqual(['alpha']);
        expect(kindList(records, 'skills', 'rejected')).toEqual([]);
        expect(kindList(records, 'plugins', 'cplug')).toEqual([]);
    });

    it('a folder with no open submission wears the non stage words', () => {
        const mine = buildRecords(input([], folders, { checkOf: (loc) => (loc === 'skill:alpha' ? { ok: true, at: '2026-10-06T00:00:00Z' } : loc === 'skill:zeta' ? { ok: false, at: '2026-10-06T00:00:00Z' } : null) }));
        const words = Object.fromEntries(kindList(mine, 'skills', '').map((r) => [r.name, r.wordKey]));
        expect(words).toEqual({ zeta: 'publish.page.row.check_failed', alpha: 'publish.page.row.checked_ready', mid: 'publish.page.row.on_computer' });
    });

    it('counts and dots per tab', () => {
        const stats = tabStats(records);
        expect(stats.submissions).toEqual({ count: 1, waits: true });
        expect(stats.skills).toEqual({ count: 3, waits: true });
        expect(stats.themes).toEqual({ count: 1, waits: false });
        expect(stats.mods).toEqual({ count: 0, waits: false });
        expect(stats.plugins).toEqual({ count: 2, waits: false });
    });
});
