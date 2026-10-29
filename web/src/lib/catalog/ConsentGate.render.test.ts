/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import InstallSheet from './InstallSheet.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { cardView } from './card';
import type { CatalogHost } from './catalog';
import type { InstallPreview, InstallRequest } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const WITH_SCRIPTS: InstallPreview = {
    body: '# tidy\nit tidies things',
    files: [
        { path: 'SKILL.md', size: 24 },
        { path: 'scripts/run.sh', size: 100 },
        { path: 'bin/go', size: 50, exec: true },
    ],
    publisher: 'alex',
    version: '1.0',
    digest: 'abc123def456',
    digest_prefix: 'abc123',
    body_sha: 'sha-of-the-text',
    total_bytes: 174,
    review: {
        status: 'reviewed',
        summary: 'it runs a shell command',
        warnings: [{ kind: 'shell_exec', detail: 'calls bash' }],
    },
};

const NO_SCRIPTS: InstallPreview = {
    ...WITH_SCRIPTS,
    files: [{ path: 'SKILL.md', size: 24 }],
};

interface Recorder {
    host: CatalogHost;
    installs: InstallRequest[];
}

function hostFor(preview: InstallPreview, install?: () => Promise<never>): Recorder {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    const installs: InstallRequest[] = [];
    const host = {
        listItems: refuse,
        refreshIndex: refuse,
        listInstalled: refuse,
        previewInstall: () => Promise.resolve(preview),
        install: (request: InstallRequest) => {
            installs.push(request);
            return install ? install() : Promise.resolve({ install_id: 'i1' });
        },
        uninstall: refuse,
        item: refuse,
        patchInstalled: refuse,
        applyUpdate: refuse,
        runningSessions: () => [],
        oneShot: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
    return { host, installs };
}

let sheet: Record<string, unknown> | null = null;

async function open(host: CatalogHost, close = vi.fn()): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    sheet = mount(InstallSheet, {
        target,
        props: {
            card: cardView({ id: 'a/b', name: 'tidy' }, false),
            host,
            t,
            close,
        } as never,
    }) as never;
    await new Promise((resolve) => setTimeout(resolve, 0));
}

function confirm(): HTMLButtonElement {
    return document.querySelector('.modal-btn-primary') as HTMLButtonElement;
}

function checkbox(): HTMLInputElement | null {
    return document.querySelector('.consent__accept input');
}

afterEach(() => {
    if (sheet) unmount(sheet as never);
    sheet = null;
    document.body.innerHTML = '';
});

describe('what the sheet shows before the button can be pressed', () => {
    test('the review sits ABOVE the skill text and ABOVE the file list', async () => {
        await open(hostFor(WITH_SCRIPTS).host);
        const order = [...document.querySelectorAll('.cat-review, .sheet__body, .sheet__files')]
            .map((node) => node.className.split(' ')[0]);
        expect(order).toEqual(['cat-review', 'sheet__body', 'sheet__files']);
    });

    test('the review says what it found, with every warning kind named', async () => {
        await open(hostFor(WITH_SCRIPTS).host);
        const review = document.querySelector('.cat-review');
        expect(review?.textContent).toContain('ai reviewed');
        expect(review?.textContent).toContain('runs shell commands');
        expect(review?.textContent).toContain('calls bash');
    });

    test('a review that did not run says "no ai review", never "nothing detected"', async () => {
        await open(hostFor({ ...WITH_SCRIPTS, review: { status: 'unavailable' } }).host);
        const review = document.querySelector('.cat-review');
        expect(review?.textContent).toContain('no ai review');
        expect((review?.textContent ?? '').toLowerCase()).not.toContain('nothing detected');
    });

    test('every executable member is MARKED in the file list and named in the gate', async () => {
        await open(hostFor(WITH_SCRIPTS).host);
        const marked = [...document.querySelectorAll('.sheet__file--exec')].map((node) =>
            (node.querySelector('.sheet__file-path')?.textContent ?? '').trim(),
        );
        expect(marked).toEqual(['scripts/run.sh', 'bin/go']);
        const listed = [...document.querySelectorAll('.consent__file')].map((node) =>
            (node.textContent ?? '').trim(),
        );
        expect(listed).toEqual(['scripts/run.sh', 'bin/go']);
    });

    test('the sentence says plainly that they run with the user permissions', async () => {
        await open(hostFor(WITH_SCRIPTS).host);
        expect(document.body.textContent).toContain(i18n.t('skill.consent.scripts_run'));
        expect(document.body.textContent).toContain(i18n.t('skill.consent.read_first'));
    });
});

describe('the gate itself', () => {
    test('the confirm is DISABLED until the box is ticked', async () => {
        await open(hostFor(WITH_SCRIPTS).host);
        expect(checkbox()).not.toBeNull();
        expect(confirm().disabled).toBe(true);
        checkbox()!.click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(confirm().disabled).toBe(false);
    });

    test('a version with NO executable member raises no gate at all', async () => {
        await open(hostFor(NO_SCRIPTS).host);
        expect(checkbox()).toBeNull();
        expect(confirm().disabled).toBe(false);
    });

    test('the tick sends a consent block naming the digest and the body sha', async () => {
        const recorder = hostFor(WITH_SCRIPTS);
        await open(recorder.host);
        checkbox()!.click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        confirm().click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(recorder.installs).toHaveLength(1);
        expect(recorder.installs[0]?.consent).toEqual({
            digest: 'abc123def456',
            body_sha: 'sha-of-the-text',
            scripts: true,
        });
    });

    test('an install with no gate sends NO consent block', async () => {
        const recorder = hostFor(NO_SCRIPTS);
        await open(recorder.host);
        confirm().click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(recorder.installs[0]?.consent).toBeUndefined();
    });

    test('a server that named no digest leaves the tick unable to unlock anything', async () => {
        await open(hostFor({ ...WITH_SCRIPTS, digest: null, body_sha: null }).host);
        expect(checkbox()?.disabled).toBe(true);
        expect(confirm().disabled).toBe(true);
        expect(document.body.textContent).toContain(i18n.t('skill.refused.unsupported'));
    });

    test('THE REFUSAL COMES AFTER THE ATTEMPT, never instead of the review', async () => {
        const recorder = hostFor(WITH_SCRIPTS, () =>
            Promise.reject({ body: { code: 'scripts_not_supported' } } as never),
        );
        await open(recorder.host);
        expect(document.querySelector('.cat-review')).not.toBeNull();
        expect(document.body.textContent).not.toContain(
            i18n.t('skill.refused.scripts_not_supported'),
        );
        checkbox()!.click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        confirm().click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(document.body.textContent).toContain(
            i18n.t('skill.refused.scripts_not_supported'),
        );
        expect(document.querySelector('.cat-review')).not.toBeNull();
    });
});
