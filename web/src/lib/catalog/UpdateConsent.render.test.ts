/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import DetailActions from './DetailActions.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { cardView } from './card';
import type { CatalogHost } from './catalog';
import type { InstalledItem, UpdateInstalledRequest } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const ROW: InstalledItem = {
    install_id: 'i1',
    item_id: 'a/b',
    scope: 'global',
    revision: 4,
    version: '0.9',
    update_available: true,
};

function refusal(body: Record<string, unknown>): Error {
    const error = new Error('HTTP 409') as Error & { status: number; body: unknown };
    error.status = 409;
    error.body = body;
    return error;
}

interface Recorder {
    host: CatalogHost;
    updates: UpdateInstalledRequest[];
    previews: number;
}

function hostFor(carried: Record<string, unknown>, previewBody?: Record<string, unknown>): Recorder {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    const recorder: Recorder = { host: null as never, updates: [], previews: 0 };
    recorder.host = {
        listItems: refuse,
        refreshIndex: refuse,
        listInstalled: refuse,
        previewInstall: () => {
            recorder.previews += 1;
            return Promise.resolve(previewBody ?? {});
        },
        install: refuse,
        uninstall: refuse,
        item: refuse,
        patchInstalled: refuse,
        applyUpdate: (_id: string, body: UpdateInstalledRequest) => {
            recorder.updates.push(body);
            if (recorder.updates.length === 1) {
                return Promise.reject(refusal({ code: 'consent_required', ...carried }));
            }
            return Promise.resolve({ ...ROW, revision: 5, update_available: false });
        },
        runningSessions: () => [],
        oneShot: refuse,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
    return recorder;
}

let panel: Record<string, unknown> | null = null;

function paint(host: CatalogHost, onLedgerChange = vi.fn()): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(DetailActions, {
        target,
        props: {
            card: cardView({ id: 'a/b', name: 'tidy', latest: '1.0' }, false),
            installed: ROW,
            rowState: { kind: 'update-available' },
            host,
            t,
            onInstall: vi.fn(),
            onLedgerChange,
        } as never,
    }) as never;
}

function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

function modalConfirm(): HTMLButtonElement {
    const buttons = [...document.querySelectorAll('.modal-btn-primary')];
    return buttons[buttons.length - 1] as HTMLButtonElement;
}

async function startUpdate(): Promise<void> {
    (document.querySelector('[data-act="update"]') as HTMLButtonElement).click();
    await settle();
    modalConfirm().click();
    await settle();
}

async function dismissEverything(): Promise<void> {
    for (let guard = 0; guard < 8; guard += 1) {
        const open = document.querySelector('.modal-overlay');
        if (!open) return;
        open.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await settle();
    }
}

afterEach(async () => {
    await dismissEverything();
    if (panel) unmount(panel as never);
    panel = null;
    document.body.innerHTML = '';
});

describe('when the new version changed the skill text', () => {
    test('the first send carries only the revision', async () => {
        const recorder = hostFor({ body: '# new text', body_sha: 'sha-new' });
        paint(recorder.host);
        await startUpdate();
        expect(recorder.updates[0]).toEqual({ expected_revision: 4 });
    });

    test('the NEW TEXT goes on screen and the confirm is locked until it is ticked', async () => {
        const recorder = hostFor({ body: '# new text', body_sha: 'sha-new' });
        paint(recorder.host);
        await startUpdate();
        expect(document.querySelector('.confirm__document')?.textContent).toBe('# new text');
        expect(document.body.textContent).toContain(i18n.t('skill.update.consent.lead'));
        expect(modalConfirm().disabled).toBe(true);
        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        expect(modalConfirm().disabled).toBe(false);
    });

    test('the second send carries the sha of exactly that text', async () => {
        const recorder = hostFor({ body: '# new text', body_sha: 'sha-new' });
        const onLedgerChange = vi.fn();
        paint(recorder.host, onLedgerChange);
        await startUpdate();
        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]).toEqual({
            expected_revision: 4,
            consent: { body_sha: 'sha-new' },
        });
        expect(onLedgerChange).toHaveBeenCalledWith(
            'a/b',
            expect.objectContaining({ revision: 5, update_available: false }),
        );
    });

    test('a 409 that named no text falls back to a PREVIEW for it', async () => {
        const recorder = hostFor({}, { body: '# from preview', body_sha: 'sha-preview' });
        paint(recorder.host);
        await startUpdate();
        expect(recorder.previews).toBe(1);
        expect(document.querySelector('.confirm__document')?.textContent).toBe('# from preview');
        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]?.consent).toEqual({ body_sha: 'sha-preview' });
    });

    test('with NO text anywhere the tick is refused and nothing is sent again', async () => {
        const recorder = hostFor({}, {});
        paint(recorder.host);
        await startUpdate();
        expect(document.body.textContent).toContain(i18n.t('skill.update.consent.unavailable'));
        expect((document.querySelector('.confirm__accept input') as HTMLInputElement).disabled)
            .toBe(true);
        expect(modalConfirm().disabled).toBe(true);
        expect(recorder.updates).toHaveLength(1);
    });

    test('CANCELLING leaves the server sentence on screen, not a quiet success', async () => {
        const recorder = hostFor({ body: '# new text', body_sha: 'sha-new' });
        paint(recorder.host);
        await startUpdate();
        const buttons = [...document.querySelectorAll('.modal-overlay .modal-btn')] as HTMLButtonElement[];
        buttons.find((button) => !button.classList.contains('modal-btn-primary'))?.click();
        await settle();
        expect(recorder.updates).toHaveLength(1);
        expect(document.querySelector('.acts__refusal')?.textContent).toBe(
            i18n.t('skill.refused.consent_required'),
        );
    });
});

describe('the consent block the second send carries', () => {
    test('it names the FOLDER DIGEST the 409 showed, beside the sha', async () => {
        const recorder = hostFor({
            body: '# new text',
            body_sha: 'sha-new',
            digest: 'digest-new',
        });
        paint(recorder.host);
        await startUpdate();
        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]).toEqual({
            expected_revision: 4,
            consent: { body_sha: 'sha-new', digest: 'digest-new' },
        });
    });

    test('a SCRIPT-BEARING version lists the files and carries scripts: true', async () => {
        const recorder = hostFor({
            body: '# new text',
            body_sha: 'sha-new',
            digest: 'digest-new',
            script_files: ['scripts/run.sh', 'bin/go'],
        });
        paint(recorder.host);
        await startUpdate();
        const listed = [...document.querySelectorAll('.confirm__line')].map((node) =>
            (node.textContent ?? '').trim(),
        );
        expect(listed).toEqual(['scripts/run.sh', 'bin/go']);
        expect(document.body.textContent).toContain(i18n.t('skill.consent.scripts_run'));
        expect(document.body.textContent).toContain(i18n.t('skill.consent.checkbox'));
        expect(modalConfirm().disabled).toBe(true);

        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]).toEqual({
            expected_revision: 4,
            consent: { body_sha: 'sha-new', digest: 'digest-new', scripts: true },
        });
    });

    test('NEGATIVE CONTROL: no executable member, no scripts flag at all', async () => {
        const recorder = hostFor({
            body: '# new text',
            body_sha: 'sha-new',
            digest: 'digest-new',
            script_files: [],
        });
        paint(recorder.host);
        await startUpdate();
        expect(document.querySelectorAll('.confirm__line')).toHaveLength(0);
        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]?.consent).not.toHaveProperty('scripts');
    });

    test('the digest is the NEW sheet\'s, never one left over from before', async () => {
        const recorder = hostFor(
            { body: '# new text', body_sha: 'sha-new', digest: 'digest-new' },
            { body: '# stale', body_sha: 'sha-stale', digest: 'digest-stale' },
        );
        paint(recorder.host);
        await startUpdate();
        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.previews).toBe(0);
        expect(recorder.updates[1]?.consent).toEqual({
            body_sha: 'sha-new',
            digest: 'digest-new',
        });
    });

    test('a 409 carrying no text takes the digest from the FRESH preview', async () => {
        const recorder = hostFor(
            {},
            { body: '# from preview', body_sha: 'sha-preview', digest: 'digest-preview' },
        );
        paint(recorder.host);
        await startUpdate();
        expect(recorder.previews).toBe(1);
        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]?.consent).toEqual({
            body_sha: 'sha-preview',
            digest: 'digest-preview',
        });
    });
});
