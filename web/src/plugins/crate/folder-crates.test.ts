/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { resourcePush } from '../sdk';
import { setLocale, t } from '../../lib/i18n/index.svelte';
import type { Fetcher } from './crate-api';
import CratePanel from './CratePanel.svelte';
import { pickCrate, sidecarHex } from './folder-crates-api';

const opened = vi.hoisted(() => [] as Array<{ source: unknown; subject: unknown }>);
vi.mock('../sdk', async (original) => ({
    ...(await original<Record<string, unknown>>()),
    openModal: vi.fn(async (_component: unknown, props: { source: unknown; subject: unknown }) => {
        opened.push({ source: props.source, subject: props.subject });
        return null;
    }),
}));

setLocale('en');

const SUMMARY = {
    folders: { primary: { path: '/state/crates', state: 'ok', reason: null, free_bytes: 5 * 1024 ** 3 }, second: null },
    encrypt_default: false, recipients: [], running_job: null, bundles: 1,
};
const HEX = 'ab'.repeat(32);

interface Call {
    path: string;
    method: string;
    init: RequestInit | undefined;
}

function world(): { fetcher: Fetcher; calls: Call[]; crates: Array<Record<string, unknown>> } {
    const calls: Call[] = [];
    const crates: Array<Record<string, unknown>> = [
        { name: 'crate-20261017T000000Z-project-1a2b3c4d.crate', size: 2048, mtime: 1792000000, share: false, encrypted: false, sha256_sidecar: null, bundle_id: 'crate-20261017T000000Z-project-1a2b3c4d' },
        { name: 'crate-20261019T000000Z-project-9f8e7d6c.crate', size: 4096, mtime: 1792100000, share: false, encrypted: false, sha256_sidecar: null, bundle_id: null },
        { name: 'share-20261019T000000Z-session-11223344.crate.age', size: 512, mtime: 1792100100, share: true, encrypted: true, sha256_sidecar: null, bundle_id: null },
    ];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const method = init?.method ?? 'GET';
        calls.push({ path, method, init });
        if (path === '/cplugs/crate/summary') return SUMMARY;
        if (path === '/cplugs/crate/bundles') return { bundles: [] };
        if (path === '/cplugs/crate/folders/primary/crates' && method === 'GET') return { crates };
        if (path === '/cplugs/crate/folders/primary/crates/upload') {
            const name = (init!.headers as Record<string, string>)['X-Crate-Name']!;
            crates.push({ name, size: 7, mtime: 1792200000, share: false, encrypted: false, sha256_sidecar: null, bundle_id: null });
            return { name, size: 7, sha256: HEX, sidecar: true };
        }
        throw new Error(`no route for ${method} ${path}`);
    }) as unknown as Fetcher;
    return { fetcher, calls, crates };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) {
        await new Promise((done) => setTimeout(done, 5));
        await Promise.resolve();
        flushSync();
    }
}

const mounted: Array<Record<string, unknown>> = [];

async function open(fetcher: Fetcher): Promise<HTMLElement> {
    const target = document.createElement('div');
    document.body.append(target);
    mounted.push(mount(CratePanel as never, { target, props: { fetcher } }) as Record<string, unknown>);
    await settle();
    return target;
}

afterEach(() => {
    for (const instance of mounted.splice(0)) unmount(instance);
    document.body.innerHTML = '';
    opened.length = 0;
    resourcePush().store.closed();
});

describe('found in the crate folders', () => {
    test('lists only unrecorded crates, and restore opens the dialog on the folder and name', async () => {
        const { fetcher } = world();
        const target = await open(fetcher);
        const rows = [...target.querySelectorAll('[data-crt-found-row]')].map((r) => r.getAttribute('data-crt-found-row'));
        expect(rows).toEqual(['share-20261019T000000Z-session-11223344.crate.age', 'crate-20261019T000000Z-project-9f8e7d6c.crate']);
        const share = target.querySelector('[data-crt-found-row^="share-"]')!.textContent!;
        expect(share).toContain(t('cplug.crate.found.share'));
        expect(share).toContain(t('cplug.crate.found.encrypted'));

        target.querySelector<HTMLElement>('[data-crt-restore-found="crate-20261019T000000Z-project-9f8e7d6c.crate"]')!.click();
        await settle();
        expect(opened).toEqual([{ source: { folder: 'primary', name: 'crate-20261019T000000Z-project-9f8e7d6c.crate' },
            subject: 'crate-20261019T000000Z-project-9f8e7d6c.crate' }]);
    });

    test('the picker sends the file with its name and checksum, re-reads the list and opens the dialog on it', async () => {
        const { fetcher, calls } = world();
        const target = await open(fetcher);
        const crate = new File(['crate-bytes'], 'crate-20261019T010101Z-project-aabbccdd.crate');
        const sum = new File([`${HEX.toUpperCase()}  ${crate.name}\n`], `${crate.name}.sha256`);
        const input = target.querySelector<HTMLInputElement>('[data-crt-picker]')!;
        Object.defineProperty(input, 'files', { value: [crate, sum], configurable: true });
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();

        const upload = calls.find((c) => c.path.endsWith('/upload'))!;
        expect(upload.method).toBe('POST');
        expect(upload.init!.body).toBe(crate);
        expect(upload.init!.headers).toEqual({ 'Content-Type': 'application/octet-stream', 'X-Crate-Name': crate.name, 'X-Crate-Sha256': HEX });
        expect(target.querySelector(`[data-crt-found-row="${crate.name}"]`)).not.toBeNull();
        expect(opened.at(-1)).toEqual({ source: { folder: 'primary', name: crate.name }, subject: crate.name });
    });

    test('a pick that is not a crate, or has a bad checksum file, sends nothing and says why', async () => {
        const { fetcher, calls } = world();
        const target = await open(fetcher);
        const input = target.querySelector<HTMLInputElement>('[data-crt-picker]')!;
        Object.defineProperty(input, 'files', { value: [new File(['x'], 'notes.txt')], configurable: true });
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        expect(target.querySelector('[data-crt-problem]')!.textContent).toBe(t('cplug.crate.error.not_a_crate'));

        const crate = new File(['x'], 'crate-20261019T010101Z-project-aabbccdd.crate');
        Object.defineProperty(input, 'files', { value: [crate, new File(['nope'], `${crate.name}.sha256`)], configurable: true });
        input.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        expect(target.querySelector('[data-crt-problem]')!.textContent).toBe(t('cplug.crate.error.bad_checksum_file'));
        expect(calls.some((c) => c.path.endsWith('/upload'))).toBe(false);
    });

    test('pickCrate pairs the checksum file and sidecarHex reads its first word', () => {
        const crate = new File(['x'], 'crate-a-1234.crate');
        const sum = new File(['x'], 'crate-a-1234.crate.sha256');
        expect(pickCrate([sum, crate])).toEqual({ crate, sidecar: sum });
        expect(pickCrate([sum])).toBeNull();
        expect(sidecarHex(`${HEX.toUpperCase()}  crate-a-1234.crate\n`)).toBe(HEX);
        expect(sidecarHex('short')).toBeNull();
    });
});
