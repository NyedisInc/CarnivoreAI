/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { ApiError } from '../sdk';
import { setLocale, t } from '../../lib/i18n/index.svelte';
import type { Fetcher } from './crate-api';
import { parseImportReceipt } from './import-receipt';
import ImportDialog from './ImportDialog.svelte';
import ImportResult from './ImportResult.svelte';
import plans from './import-plans.fixture.json';

setLocale('en');

const RECEIPT = {
    import_id: 'imp-20261018T120000Z-1a2b3c4d', state: 'done', project: { id: 4, name: 'Proj One', root: '/Users/me/proj1', action: 'create' },
    sessions: [
        { session_uuid: 'aaaaaaaa-0000-4000-8000-000000000001', asleep: true, conversation_id: 'conv-a' },
        { session_uuid: 'bbbbbbbb-0000-4000-8000-000000000002', asleep: true, conversation_id: 'conv-b' },
    ],
    conversations: [{ id: 'conv-a', title: 'first chat', class: 'write', resume: 'native' }, { id: 'conv-b', title: null, class: 'write', resume: 'native' }],
    warnings: [{ code: 'board_unlinked', detail: 'b: task 9' }], not_restored: [{ what: 'terminal grids', why: 'keyed by a tmux name' }],
    plugin_data: { boards: [{ slug: 'b', state: 'beside', path: '/boards/.crate-import/b' }] },
    project_files: { path: '/Users/me/proj1-20261018', patch: true },
};

const mounted: Array<Record<string, unknown>> = [];
afterEach(() => {
    while (mounted.length) unmount(mounted.pop() as never);
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

function show(component: unknown, props: Record<string, unknown>): HTMLElement {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(component as never, { target, props }) as Record<string, unknown>);
    flushSync();
    return target;
}

describe('import result', () => {
    test('lists the sessions asleep and wakes one through the existing route with its local uuid', async () => {
        const calls: Array<{ path: string; method: string }> = [];
        const fetcher = (async (path: string, init?: RequestInit) => {
            calls.push({ path, method: init?.method ?? 'GET' });
            return { status: 'started', detail: '' };
        }) as unknown as Fetcher;
        const receipt = parseImportReceipt(RECEIPT)!;
        const target = show(ImportResult, { receipt, fetcher });
        expect(target.querySelector('[data-crt-result-heading]')!.textContent).toContain(t('cplug.crate.import.result.sessions', { count: 2, project: 'Proj One' }));
        expect(target.querySelectorAll('[data-crt-result-session]').length).toBe(2);
        expect(target.querySelector('[data-crt-result-session] .crt-tty__name')!.textContent).toBe('first chat');
        expect(target.querySelector('[data-crt-result-beside]')).not.toBeNull();
        expect(target.querySelector('[data-crt-result-patch]')).not.toBeNull();
        const wake = target.querySelector('[data-crt-result-wake="aaaaaaaa-0000-4000-8000-000000000001"]') as HTMLButtonElement;
        wake.click();
        await settle();
        expect(calls).toEqual([{ path: '/sessions/aaaaaaaa-0000-4000-8000-000000000001/wake', method: 'POST' }]);
        expect(target.querySelector('[data-crt-result-session="aaaaaaaa-0000-4000-8000-000000000001"] [data-crt-result-status]')!.textContent).toBe(t('cplug.crate.import.result.awake'));
        expect(wake.disabled).toBe(true);
        expect(target.querySelector('[data-crt-result-session="bbbbbbbb-0000-4000-8000-000000000002"] [data-crt-result-status]')!.textContent).toBe(t('cplug.crate.import.result.asleep'));
    });

    test('a refused wake shows the refusal and the button stays usable', async () => {
        const fetcher = (async () => { throw new ApiError('a wake is in flight', 409); }) as unknown as Fetcher;
        const target = show(ImportResult, { receipt: parseImportReceipt(RECEIPT)!, fetcher });
        const wake = target.querySelector('[data-crt-result-wake]') as HTMLButtonElement;
        wake.click();
        await settle();
        expect(target.querySelector('[data-crt-result-status]')!.textContent).not.toBe(t('cplug.crate.import.result.awake'));
        expect(target.querySelector('[data-crt-result-status]')!.textContent).not.toBe(t('cplug.crate.import.result.waking'));
        expect(wake.disabled).toBe(false);
    });

    test('a restore with nothing left to write says so', () => {
        const receipt = parseImportReceipt({ ...RECEIPT, state: 'noop', sessions: [], plugin_data: {}, project_files: {}, warnings: [], not_restored: [] })!;
        const target = show(ImportResult, { receipt });
        expect(target.querySelector('[data-crt-result-heading]')!.textContent).toContain(t('cplug.crate.import.result.nothing', { project: 'Proj One' }));
        expect(target.querySelector('[data-crt-result-session]')).toBeNull();
    });

    test('the dialog shows the result when the job ends done with a receipt, and keeps the job outcome when it has none', async () => {
        for (const [result, expected] of [[RECEIPT, true], [null, false]] as const) {
            const calls: string[] = [];
            const fetcher = (async (path: string, init?: RequestInit) => {
                calls.push(`${init?.method ?? 'GET'} ${path}`);
                if (path.endsWith('/imports/plan')) return { ...plans.own, start_available: true };
                if (path.endsWith('/imports')) return { job_id: 'job-9', import_id: RECEIPT.import_id };
                return { job_id: 'job-9', kind: 'import', state: 'done', result };
            }) as unknown as Fetcher;
            const target = show(ImportDialog, { source: { bundleId: 'crate-1' }, subject: 'x', close: () => {}, fetcher });
            await settle();
            (target.querySelector('[data-crt-go]') as HTMLButtonElement).click();
            await settle();
            expect(target.querySelector('[data-crt-import-result]') !== null).toBe(expected);
            expect(target.querySelector('[data-crt-done]') !== null).toBe(!expected);
        }
    });
});
