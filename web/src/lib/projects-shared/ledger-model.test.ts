import { describe, expect, test } from 'vitest';
import type { HistorySession } from './history-api';
import { group, session } from './test-fixtures';
import {
    ageLabel,
    companyActions,
    companyCards,
    companyKeyOf,
    diskTag,
    hiddenProjectCount,
    archivedProjectCount,
    isAutomatedOnly,
    primaryAction,
    projectActions,
    projectLead,
    projectRows,
    sessionGroups,
    transcriptPath,
} from './ledger-model';

describe('hidden projects', () => {
    test('automated-only projects are hidden, archived ones show only under archived; a mixed one is never hidden', () => {
        const archived = group({ name: 'old', project: { ...group({}).project!, name: 'old', archived_at: '2026-01-01T00:00:00Z' } });
        const robots = group({ name: 'briefing', session_total: 3, counts: { closed: 3 }, automated_counts: { closed: 3 } });
        const mixed = group({ name: 'mixed', session_total: 3, counts: { closed: 3 }, automated_counts: { closed: 1 } });
        const empty = group({ name: 'empty' });
        expect(isAutomatedOnly(robots)).toBe(true);
        expect(isAutomatedOnly(mixed)).toBe(false);
        expect(isAutomatedOnly(empty)).toBe(false);
        expect(hiddenProjectCount([archived, robots, mixed, empty])).toBe(1);
        expect(archivedProjectCount([archived, robots, mixed, empty])).toBe(1);
        const opts = { query: '', showHidden: false, sort: 'name' as const, fallbackName: 'none' };
        const all = [archived, robots, mixed, empty];
        expect(projectRows(all, opts).map((r) => r.name)).toEqual(['empty', 'mixed']);
        expect(projectRows(all, { ...opts, showHidden: true }).map((r) => r.name)).toEqual(['briefing', 'empty', 'mixed']);
        expect(projectRows(all, { ...opts, showArchived: true }).map((r) => r.name)).toEqual(['empty', 'mixed', 'old']);
    });

    test('counts leave out automated runs until hidden is shown, and removed joins closed only then', () => {
        const g = group({ session_total: 6, counts: { running: 1, asleep: 1, closed: 2, removed: 1, unknown: 1 }, automated_counts: { running: 1, closed: 1 } });
        const plain = projectRows([g], { query: '', showHidden: false, sort: 'recent', fallbackName: '' })[0]!;
        expect([plain.running, plain.sleeping, plain.closed]).toEqual([0, 1, 2]);
        const all = projectRows([g], { query: '', showHidden: true, sort: 'recent', fallbackName: '' })[0]!;
        expect([all.running, all.sleeping, all.closed]).toEqual([1, 1, 4]);
    });

    test('search matches the name only and recent sort puts the newest first', () => {
        const a = group({ name: 'alpha', last_activity_at: '2026-09-01T00:00:00Z' });
        const b = group({ name: 'beta', last_activity_at: '2026-09-20T00:00:00Z' });
        const opts = { query: '', showHidden: false, sort: 'recent' as const, fallbackName: '' };
        expect(projectRows([a, b], opts).map((r) => r.name)).toEqual(['beta', 'alpha']);
        expect(projectRows([a, b], { ...opts, query: 'ALP' }).map((r) => r.name)).toEqual(['alpha']);
        expect(projectRows([a, b], { ...opts, query: '/x/alpha' })).toEqual([]);
    });
});

describe('sessions in a project', () => {
    const g = group({
        session_total: 5,
        sessions: [
            session({ session_uuid: 'r', state: 'running' }),
            session({ session_uuid: 'z', state: 'asleep' }),
            session({ session_uuid: 'c', state: 'closed' }),
            session({ session_uuid: 'x', state: 'removed' }),
            session({ session_uuid: 'a', state: 'closed', kind: 'automated' }),
        ],
    });

    test('removed and automated sessions wait behind show hidden', () => {
        const ids = (o: { showHidden: boolean }) => {
            const out = sessionGroups(g, { ...o, query: '' });
            return [out.running, out.sleeping, out.closed].map((l) => l.map((s) => s.session_uuid));
        };
        expect(ids({ showHidden: false })).toEqual([['r'], ['z'], ['c']]);
        expect(ids({ showHidden: true })).toEqual([['r'], ['z'], expect.arrayContaining(['c', 'x', 'a'])]);
    });

    test('inside an automated-only project the runs are the content', () => {
        const robots = group({ session_total: 1, counts: { closed: 1 }, automated_counts: { closed: 1 }, sessions: [session({ kind: 'automated' })] });
        expect(sessionGroups(robots, { showHidden: false, query: '' }).closed).toHaveLength(1);
    });
});

describe('the one primary action', () => {
    test.each([
        ['running, held here', { state: 'running', live_session_id: 'ses_1' }, 'open'],
        ['running on another host, not held', { state: 'running', host_key: 'hostb' }, 'none'],
        ['asleep', { state: 'asleep' }, 'wake'],
        ['closed, transcript on disk', { claude_session_uuid: 'c', has_transcript: true }, 'resume'],
        ['closed, transcript gone', { claude_session_uuid: 'c' }, 'none'],
        ['closed, never had a conversation', {}, 'restart'],
        ['removed, transcript on disk', { state: 'removed', claude_session_uuid: 'c', has_transcript: true }, 'resume'],
    ] as const)('%s', (_name, patch, expected) => {
        expect(primaryAction(session(patch as Partial<HistorySession>)).id).toBe(expected);
    });

    test('a disabled resume says why', () => {
        expect(primaryAction(session({ claude_session_uuid: 'c' })).disabledReasonKey).toBe('projects.page.primary.gone_reason');
    });

    test('the disk tag is drawn only on a stopped session with a conversation', () => {
        expect(diskTag(session({ state: 'running', claude_session_uuid: 'c' }))).toBeNull();
        expect(diskTag(session({}))).toBeNull();
        expect(diskTag(session({ claude_session_uuid: 'c', has_transcript: true }))).toBe('on-disk');
        expect(diskTag(session({ claude_session_uuid: 'c' }))).toBe('gone');
    });
});

test('project actions: hide leads the rule, a hidden project offers unhide and no new session', () => {
    expect(projectActions({ archived_at: null, root: '/a' }).map((a) => a.id)).toEqual([
        'new-session',
        'rename-project',
        'copy-path',
        'load-blueprint',
        'migrate-project',
        'set-image',
        'regenerate-art',
        'add-to-company',
        'archive-project',
        'delete-project',
    ]);
    expect(projectActions({ archived_at: 'x', root: '/a' }).map((a) => a.id)).toEqual(['rename-project', 'copy-path', 'set-image', 'regenerate-art', 'add-to-company', 'pack-folder', 'unarchive-project', 'delete-project']);
    expect(projectActions({ archived_at: null, has_image: true }).map((a) => a.id)).toContain('remove-image');
    expect(projectActions({ archived_at: null, has_image: false }).map((a) => a.id)).not.toContain('remove-image');
    expect(projectActions({ archived_at: null, root: null }).map((a) => a.id)).not.toContain('copy-path');
    expect(projectLead({ archived_at: null }).id).toBe('new-session');
    expect(projectLead({ archived_at: 'x' }).id).toBe('unarchive-project');
});

test('transcript path follows the literal cwd; absent unless the file is on disk', () => {
    const on = session({ working_dir: '/Users/a/My Docs', claude_session_uuid: 'abc', has_transcript: true });
    expect(transcriptPath(on)).toBe('~/.claude/projects/-Users-a-My-Docs/abc.jsonl');
    expect(transcriptPath({ ...on, has_transcript: false })).toBeNull();
});

test('age labels step minutes, hours, days, then a date', () => {
    const f = { minutes: (n: number) => `${n}m`, hours: (n: number) => `${n}h`, days: (n: number) => `${n}d`, date: () => 'date' };
    const now = Date.parse('2026-09-29T12:00:00Z');
    const at = (mins: number) => new Date(now - mins * 60_000).toISOString();
    expect([5, 190, 2 * 1440, 9 * 1440].map((m) => ageLabel(at(m), now, f))).toEqual(['5m', '3h', '2d', 'date']);
    expect(ageLabel(null, now, f)).toBe('');
});

describe('companies', () => {
    const acme = { id: 2, name: 'Acme', project_count: 0 };
    const zed = { id: 1, name: 'zed co', project_count: 0 };
    const inCompany = (name: string, id: number | null) =>
        group({ name, project: { ...group({ name }).project!, company_id: id, company_name: id === null ? null : 'x' } });

    test('a group belongs under its company id, or orphaned (no company, or no project at all)', () => {
        expect(companyKeyOf(inCompany('a', 2))).toBe('2');
        expect(companyKeyOf(inCompany('b', null))).toBe('orphaned');
        expect(companyKeyOf(group({ name: 'c' }))).toBe('orphaned');
        expect(companyKeyOf({ ...group({ name: 'd' }), project: null })).toBe('orphaned');
    });

    test('the cards are A-Z ignoring case, no orphaned card, counting what the list below would show', () => {
        const hidden = group({ name: 'h', project: { ...group({ name: 'h' }).project!, company_id: 2, archived_at: 'x' } });
        const groups = [inCompany('a', 2), inCompany('b', 2), hidden, inCompany('c', 1), inCompany('d', null)];
        const cards = (showHidden: boolean, query = '', showArchived = false) =>
            companyCards([zed, acme], groups, showHidden, query, 'all', showArchived).map((c) => [c.name, c.count]);
        expect(cards(false)).toEqual([['Acme', 2], ['zed co', 1]]);
        expect(cards(true)).toEqual([['Acme', 2], ['zed co', 1]]);
        expect(cards(false, '', true)).toEqual([['Acme', 3], ['zed co', 1]]);
        expect(cards(false, ' ZED')).toEqual([['zed co', 1]]);
        expect(companyCards([], [], false)).toEqual([]);
        const withImage = companyCards([{ ...acme, has_image: true, image_rev: 'r1' }, zed], [], false);
        expect(withImage.map((c) => [c.hasImage, c.imageUrl !== null])).toEqual([[true, true], [false, false]]);
        expect(companyActions(true).map((a) => a.id)).toEqual(['rename-company', 'migrate-company', 'set-image', 'remove-image', 'regenerate-art', 'delete-company']);
        expect(companyActions().map((a) => a.id)).toEqual(['rename-company', 'migrate-company', 'set-image', 'regenerate-art', 'delete-company']);
    });

    test('the cards follow the whole page filter: own name, a project name, the state facet, no match', () => {
        const run = (name: string, id: number, counts: Record<string, number>) =>
            group({ name, counts, project: { ...group({ name }).project!, company_id: id, company_name: 'x' } });
        const groups = [run('alpha', 2, { running: 1 }), run('beta', 2, { closed: 1 }), run('gamma', 1, { closed: 1 })];
        const names = (query: string, state = 'all') => companyCards([zed, acme, { id: 3, name: 'Empty', project_count: 0 }], groups, false, query, state).map((c) => c.name);
        expect(names('')).toEqual(['Acme', 'Empty', 'zed co']);
        expect(names('zed')).toEqual(['zed co']);
        expect(names('beta')).toEqual(['Acme']);
        expect(names('nothing')).toEqual([]);
        expect(names('', 'running')).toEqual(['Acme']);
        expect(names('', 'quiet')).toEqual(['Acme', 'zed co']);
        expect(names('beta', 'running')).toEqual([]);
    });

    test('+ company is one item whose submenu lists companies A-Z, marks the current, then new company', () => {
        const items = projectActions({ archived_at: null, root: null, company_id: 1 }, [zed, acme]);
        expect(items.filter((i) => i.children).map((i) => i.id)).toEqual(['add-to-company']);
        const company = items.find((i) => i.id === 'add-to-company')!;
        expect(company.labelKey).toBe('projects.page.action.add_company');
        expect(company.children!.map((c) => c.id)).toEqual(['set-company:2', 'set-company:1', 'new-company-for-project']);
        expect(company.children!.map((c) => c.label)).toEqual(['Acme', 'zed co', undefined]);
        expect(company.children!.map((c) => c.checked)).toEqual([false, true, undefined]);
        expect(items.map((i) => i.id)).toContain('remove-from-company');
        expect(projectActions({ archived_at: null, company_id: null }, [acme]).map((i) => i.id)).not.toContain('remove-from-company');
        expect(projectActions({ archived_at: null }).find((i) => i.id === 'add-to-company')!.children!.map((c) => c.id)).toEqual(['new-company-for-project']);
    });
});
