import { describe, expect, it, vi } from 'vitest';
import { runPackFlow } from './pack-flow';
import type { HistoryApi } from './history-api';
import { confirmText, onlyNeedsLocalOnly, packTag, sizeWord, type PackAnswer } from './pack-model';
import { projectActions, projectLead } from './ledger-model';

const t = (key: string, params?: Record<string, unknown> | null): string =>
    params ? `${key} ${JSON.stringify(params)}` : key;

const plan = (over: Partial<PackAnswer> = {}): PackAnswer => ({
    kind: 'pack', ok: true, checks: [{ id: 'archived', ok: true, message: 'ok' }], warnings: [],
    sizes: { logical_bytes: 1_420_000_000, file_count: 6084, estimate_low: 300_000_000, estimate_high: 500_000_000 },
    repos: [{ path: '.' }], local_only: [], fingerprint: 'fp1', job: null, ...over,
});

describe('pack tags and menu items', () => {
    it('shows packed with its size, and a modified archive as a warning with its sentence', () => {
        expect(packTag({ state: 'packed', archive_bytes: 412_000_000, integrity: { status: 'ok', message: '', full: false } }, t)?.text)
            .toBe('projects.page.tag.packed {"size":"412 mb"}');
        const warned = packTag({ state: 'packed', archive_bytes: 5, integrity: { status: 'modified', message: 'changed outside', full: false } }, t);
        expect(warned).toMatchObject({ warn: true, title: 'changed outside' });
        expect(packTag(null, t)).toBeNull();
        expect(packTag({ state: 'packing', progress: { phase: 'hashing', percent: 37 } }, t)?.text).toContain('37');
        expect(sizeWord(1_420_000_000)).toBe('1.4 gb');
    });

    it('offers pack on a hidden folder, unpack on a packed one, and unhide only when not packed', () => {
        const ids = (p: Parameters<typeof projectActions>[0]) => projectActions(p).map((a) => a.id);
        expect(ids({ archived_at: 'x' })).toContain('pack-folder');
        expect(ids({ archived_at: null })).not.toContain('pack-folder');
        const packed = ids({ archived_at: 'x', storage: { state: 'packed' } });
        expect(packed).toContain('unpack-folder');
        expect(packed).not.toContain('unarchive-project');
        expect(packed).not.toContain('pack-folder');
        expect(ids({ archived_at: 'x', storage: { state: 'packing' } })).toEqual(expect.not.arrayContaining(['pack-folder', 'unarchive-project']));
        expect(ids({ archived_at: 'x', storage: { state: 'unpacked' } })).toContain('unarchive-project');
        expect(projectLead({ archived_at: 'x', storage: { state: 'packed' } }).id).toBe('unpack-folder');
    });

    it('words the plan and the only-copy rule', () => {
        const text = confirmText('old', plan({ local_only: ['.: no remote'] }), t);
        expect(text.message).toContain('"size":"1.4 gb"');
        expect(text.detail).toContain('projects.page.pack.only_copy');
        const refused = plan({ ok: false, checks: [{ id: 'git_local_only', ok: false, message: 'x' }] });
        expect(onlyNeedsLocalOnly(refused)).toBe(true);
    });
});

describe('the pack flow', () => {
    const api = (planFn: ReturnType<typeof vi.fn>, applyFn: ReturnType<typeof vi.fn>, yes = true): HistoryApi =>
        ({ pack: { plan: planFn, apply: applyFn }, confirm: vi.fn().mockResolvedValue(yes) }) as unknown as HistoryApi;

    it('plans, confirms, then applies quoting the fingerprint', async () => {
        const apply = vi.fn().mockResolvedValue(plan());
        const out = await runPackFlow('pack', 'old', api(vi.fn().mockResolvedValue(plan()), apply), t);
        expect(apply).toHaveBeenCalledWith('pack', 'old', 'fp1', false);
        expect(out.started).toBe(true);
    });

    it('says the reasons and applies nothing when the plan refuses', async () => {
        const apply = vi.fn();
        const refused = plan({ ok: false, checks: [{ id: 'git_clean', ok: false, message: 'branch main is 2 ahead' }] });
        const out = await runPackFlow('pack', 'old', api(vi.fn().mockResolvedValue(refused), apply), t);
        expect(out.started).toBe(false);
        expect(out.notice).toContain('branch main is 2 ahead');
        expect(apply).not.toHaveBeenCalled();
    });

    it('asks the only-copy question and re-plans with the flag', async () => {
        const first = plan({ ok: false, checks: [{ id: 'git_local_only', ok: false, message: 'x' }], local_only: ['.: no remote'] });
        const planFn = vi.fn().mockResolvedValueOnce(first).mockResolvedValueOnce(plan({ local_only: ['.: no remote'] }));
        const apply = vi.fn().mockResolvedValue(plan());
        const out = await runPackFlow('pack', 'old', api(planFn, apply), t);
        expect(planFn).toHaveBeenNthCalledWith(2, 'pack', 'old', true);
        expect(apply).toHaveBeenCalledWith('pack', 'old', 'fp1', true);
        expect(out.started).toBe(true);
    });

    it('does nothing when the person cancels', async () => {
        const apply = vi.fn();
        const out = await runPackFlow('unpack', 'old', api(vi.fn().mockResolvedValue(plan({ kind: 'unpack' })), apply, false), t);
        expect(out).toEqual({ started: false, notice: '' });
        expect(apply).not.toHaveBeenCalled();
    });
});
