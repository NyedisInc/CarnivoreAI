/** @vitest-environment jsdom */
import { readFileSync } from 'node:fs';
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import Queue from './Queue.svelte';
import FileView from './FileView.svelte';
import { AdminApi, type Fetcher } from './admin.js';
import type { AdminHost } from './admin-host.svelte.js';

const HOSTILE = '<script>alert(1)</script>';
let mounted: Array<Record<string, unknown>> = [];

afterEach(() => {
    for (const m of mounted) unmount(m);
    mounted = [];
    document.body.innerHTML = '';
});

function fetcher(fileStatus = 200): Fetcher {
    return async (url) => {
        const json = (status: number, body: unknown) => ({
            ok: status < 400, status, json: async () => body,
            headers: { get: () => 'application/json' },
        });
        if (url.includes('/file?')) {
            if (fileStatus !== 200) return json(fileStatus, { code: 'unavailable' });
            return {
                ok: true, status: 200, json: async () => null,
                text: async () => HOSTILE,
                headers: { get: () => 'text/plain; charset=utf-8' },
            };
        }
        return json(200, {
            submission_id: 'ab', kind: 'theme',
            submitter: {
                handle: 'sam', provider: 'github', email: 's@x.test',
                account_age_days: 9, prior_approvals: 2,
            },
            files: [{ path: 'theme.json', size: 12 }],
        });
    };
}

function hostFor(api: AdminApi): AdminHost {
    return {
        api, queueLoaded: true, busy: false, queueStatus: 'in_review', selectQueueStage: () => {},
        submissions: [{ submission_id: 'ab', name: 'night', kind: 'theme', file_count: 1 }],
        rejecting: '', rejectReason: '', reports: {}, loadQueue: async () => {},
    } as unknown as AdminHost;
}

const settle = async () => { for (let i = 0; i < 5; i++) { await Promise.resolve(); flushSync(); } };

describe('submissions queue and file view', () => {
    test('the queue row shows its kind badge', () => {
        mounted.push(mount(Queue, { target: document.body, props: { host: hostFor(new AdminApi(fetcher(), () => 't')) } }));
        flushSync();
        expect(document.querySelector('.admin-badge')?.textContent).toBe('theme');
    });

    test('a file with a script tag is literal text, no script element', async () => {
        mounted.push(mount(Queue, { target: document.body, props: { host: hostFor(new AdminApi(fetcher(), () => 't')) } }));
        flushSync();
        const open = [...document.querySelectorAll('button')].find((b) => b.textContent?.includes('review files'));
        open!.click();
        await settle();
        expect(document.body.textContent).toContain('sam');
        const read = [...document.querySelectorAll('button')].find((b) => b.textContent?.includes('theme.json'));
        read!.click();
        await settle();
        expect(document.querySelector('pre')?.textContent).toBe(HOSTILE);
        expect(document.querySelector('script')).toBeNull();
    });

    test('a 503 on the file read shows its own sentence', async () => {
        mounted.push(mount(Queue, { target: document.body, props: { host: hostFor(new AdminApi(fetcher(503), () => 't')) } }));
        flushSync();
        [...document.querySelectorAll('button')].find((b) => b.textContent?.includes('review files'))!.click();
        await settle();
        [...document.querySelectorAll('button')].find((b) => b.textContent?.includes('theme.json'))!.click();
        await settle();
        expect(document.querySelector('[role=alert]')?.textContent).toContain('unavailable');
    });

    test('an image shows size and type only', () => {
        mounted.push(mount(FileView, { target: document.body, props: { file: { kind: 'image', size: 9, type: 'image/png' } } }));
        flushSync();
        expect(document.body.textContent).toContain('image/png');
        expect(document.querySelector('img')).toBeNull();
    });

    test('the submission components carry no markup sinks', () => {
        const banned = /\{@html|innerHTML|<iframe|<object|createObjectURL/;
        for (const f of ['Queue.svelte', 'SubmissionDetail.svelte', 'FileView.svelte']) {
            const src = readFileSync('src/admin/' + f, 'utf8')
                .replace(/<!--[\s\S]*?-->/g, '');
            expect(src, f).not.toMatch(banned);
        }
    });
});
