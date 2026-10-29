/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import InstallSheet from './InstallSheet.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { cardView } from './card';
import type { CatalogHost } from './catalog';
import type { InstallPreview } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

function hostFor(preview: InstallPreview): CatalogHost {
    return hostWith(() => Promise.resolve(preview));
}

function collisionHost(preview: InstallPreview): CatalogHost {
    return hostWith(() => Promise.reject({ detail: { code: 'name_taken', ...preview }, body: { detail: { code: 'name_taken', ...preview } } }));
}

function hostWith(previewInstall: () => Promise<InstallPreview>): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: refuse,
        refreshIndex: refuse,
        listInstalled: refuse,
        previewInstall,
        install: refuse,
        uninstall: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
}

let sheet: Record<string, unknown> | null = null;

async function open(host: CatalogHost): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    sheet = mount(InstallSheet, {
        target,
        props: {
            card: cardView({ id: 'a/b', name: 'tidy' }, false),
            host,
            t,
            close: vi.fn(),
        },
    } as never) as never;
    await new Promise((resolve) => setTimeout(resolve, 0));
}

function confirmButton(): HTMLButtonElement | null {
    return document.querySelector('.modal-btn-primary');
}

afterEach(() => {
    if (sheet) unmount(sheet as never);
    sheet = null;
    document.body.innerHTML = '';
});

describe('a preview the sheet does not get to choose', () => {
    test('two files claiming ONE path are both listed', async () => {
        await open(hostFor({ body: 'read me', files: [{ path: 'SKILL.md' }, { path: 'SKILL.md' }] }));
        expect(document.querySelectorAll('.sheet__file')).toHaveLength(2);
    });

    test('two ways past a collision sharing ONE name are both offered', async () => {
        await open(collisionHost({
            body: 'read me',
            choices: [
                { choice: 'rename', name: 'tidy-2' },
                { choice: 'rename', name: 'tidy-3' },
            ],
        }));
        expect(document.querySelectorAll('input[name="catalog-choice"]')).toHaveLength(2);
    });

    test('a name_taken 409 in its REAL nested shape keeps the review, the notice and the choices', async () => {
        await open(collisionHost({
            body: 'read me',
            files: [{ path: 'SKILL.md' }],
            review: {
                status: 'reviewed',
                summary: 's',
                verdict: 'flagged',
                warnings: [{ kind: 'instructions_write', detail: 'appends to CLAUDE.md', file: 'SKILL.md' }],
            },
            choices: [
                { choice: 'install_as', name: 'tidy-carnivore' },
                { choice: 'replace', name: 'tidy' },
            ],
        }));
        const text = document.body.textContent ?? '';
        expect(text).not.toContain(i18n.t('skill.review.absent'));
        expect(document.querySelector('[data-instructions-write-consent]')).not.toBeNull();
        expect(document.querySelectorAll('input[name="catalog-choice"]')).toHaveLength(2);
    });

    test('an unanswered collision keeps the install button disabled', async () => {
        await open(collisionHost({
            body: 'read me',
            choices: [
                { choice: 'rename', name: 'tidy-2' },
                { choice: 'replace', name: 'tidy' },
            ],
        }));
        expect(confirmButton()?.disabled).toBe(true);
    });
});

describe('the document being consented to', () => {
    test('the SKILL.md text is shown WHOLE, however long it is', async () => {
        const body = 'consent\n'.repeat(20000);
        await open(hostFor({ body }));
        const block = document.querySelector('.sheet__body');
        expect(block?.textContent).toHaveLength(body.length);
    });

    test('its size is stated, so the length is a fact and not a surprise', async () => {
        const body = 'x'.repeat(4096);
        await open(hostFor({ body }));
        expect(document.body.textContent).toContain(
            i18n.t('skill.sheet.body.size', { count: body.length }),
        );
    });

    test('NEGATIVE CONTROL: a preview with no body prints no block and no size', async () => {
        await open(hostFor({ files: [{ path: 'SKILL.md' }] }));
        expect(document.querySelector('.sheet__body')).toBe(null);
        expect(document.querySelectorAll('.sheet__file')).toHaveLength(1);
    });

    test('every fact the user consents to is on the sheet', async () => {
        await open(hostFor({
            body: 'read me',
            publisher: 'carnivore',
            version: '1.4.0',
            key_id: 'k1',
            pinned: true,
            index_host: 'example.invalid',
            digest_prefix: 'abcd1234',
            total_bytes: 2048,
        }));
        const text = document.body.textContent ?? '';
        for (const fact of ['carnivore', '1.4.0', 'k1', 'example.invalid', 'abcd1234']) {
            expect(text, fact).toContain(fact);
        }
        expect(text).toContain(i18n.t('skill.sheet.bytes', { count: 2048 }));
        expect(text).toContain(i18n.t('skill.sheet.pinned'));
    });

    test('no install report notice or consent line is drawn (Alex (example-owner), 2026-10-18)', async () => {
        await open(hostFor({ body: 'read me', files: [{ path: 'SKILL.md' }] }));
        expect(document.querySelector('[data-install-report-notice]')).toBe(null);
        expect((document.body.textContent ?? '').toLowerCase()).not.toContain('installs are reported');
        expect((document.body.textContent ?? '').toLowerCase()).not.toContain('privacy policy');
    });
});
