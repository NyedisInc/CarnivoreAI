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

/** An installed global copy with an update waiting. */
const ROW: InstalledItem = {
    install_id: 'i1',
    item_id: 'a/b',
    scope: 'global',
    revision: 4,
    version: '0.9',
    update_available: true,
};

function refusal(detail: Record<string, unknown>): Error {
    const error = new Error('HTTP 409') as Error & { status: number; body: unknown; detail: unknown };
    error.status = 409;
    error.detail = detail;
    error.body = { detail };
    return error;
}

/** Everything the update path was asked to send. */
interface Recorder {
    host: CatalogHost;
    updates: UpdateInstalledRequest[];
    previews: number;
}

/**
 * A host whose first update refuses `consent_required` and whose second
 * succeeds, with the 409 optionally carrying the text and the sha.
 */
function hostFor(carried: Record<string, unknown>, previewBody?: Record<string, unknown>, refuseOnce = true): Recorder {
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
            if (refuseOnce && recorder.updates.length === 1) {
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

/** Mount the action row over one host, with an update waiting. */
function paint(host: CatalogHost, onLedgerChange = vi.fn(), kind: string | undefined = undefined): void {
    const target = document.createElement('div');
    document.body.appendChild(target);
    panel = mount(DetailActions, {
        target,
        props: {
            card: cardView({ id: 'a/b', name: 'tidy', latest: '1.0', kind }, false),
            installed: ROW,
            rowState: { kind: 'update-available' },
            host,
            t,
            onInstall: vi.fn(),
            onLedgerChange,
        } as never,
    }) as never;
}

/** Let every microtask settle. */
function settle(): Promise<void> {
    return new Promise((resolve) => setTimeout(resolve, 0));
}

/** The primary control of whichever modal is open. */
function modalConfirm(): HTMLButtonElement {
    const buttons = [...document.querySelectorAll('.modal-btn-primary')];
    return buttons[buttons.length - 1] as HTMLButtonElement;
}

/** Press update and agree to the plain version confirm. */
async function startUpdate(): Promise<void> {
    (document.querySelector('[data-act="update"]') as HTMLButtonElement).click();
    await settle();
    modalConfirm().click();
    await settle();
}

/**
 * Close anything still open before the next case starts.
 *
 * TEARING THE DOM OUT DOES NOT RESOLVE A MODAL. `openModal` holds a
 * promise and an open count that only its own `close` settles, so a case
 * ending with a sheet up leaks that count into the next one, where the
 * in-flight guard then refuses to open anything at all. Escape is how a
 * person closes it, so it is how this closes it too.
 */
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

    test('DEFECT 2: a 409 with no text never asks the planner for a preview', async () => {
        const recorder = hostFor({}, { body: '# from preview', body_sha: 'sha-preview' });
        paint(recorder.host);
        await startUpdate();
        expect(recorder.previews).toBe(0);
        expect(document.body.textContent).toContain(i18n.t('skill.update.consent.unavailable'));
        expect(modalConfirm().disabled).toBe(true);
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

    test('DEFECT 1 end to end: text, sha and digest come off the wrapped {detail} 409', async () => {
        const recorder = hostFor({ body: '# wrapped', body_sha: 'sha-w', digest: 'dg-w' });
        paint(recorder.host);
        await startUpdate();
        expect(document.querySelector('.confirm__document')?.textContent).toBe('# wrapped');
        (document.querySelector('.confirm__accept input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]?.consent).toEqual({ body_sha: 'sha-w', digest: 'dg-w' });
    });
});

const FACTS = {
    id: 'a/b', name: 'b', description: 'd', version: '1.0.1', entry: 'main.py', files: 3, bytes: 900,
    permissions: [{ name: 'net.fetch', risk: 'high', reason: 'reads the health page' }],
    tools: [], network_hosts: [], lan_hosts: [], secrets: [],
};

async function cplugSheet(): Promise<Recorder> {
    const recorder = hostFor({
        body: '{"id": "a/b"}',
        body_sha: 'sha-c',
        digest: 'dg-c',
        script_files: [],
        requires_consent: true,
        cplug_facts: FACTS,
        cplug_facts_sha: 'facts-sha',
    });
    paint(recorder.host, vi.fn(), 'cplug');
    await startUpdate();
    return recorder;
}

describe('the update of a plugin (cplug)', () => {
    test('DEFECT 4: its document and declared permissions are on screen, worded as a plugin', async () => {
        await cplugSheet();
        expect(document.querySelector('.confirm__document')?.textContent).toBe('{"id": "a/b"}');
        expect(document.querySelector('.cplugfacts')?.textContent).toContain('net.fetch');
        expect(document.body.textContent).toContain(i18n.t('skill.update.consent.cplug_lead'));
        expect(document.body.textContent).not.toContain(i18n.t('skill.update.consent.lead'));
        expect(modalConfirm().disabled).toBe(true);
    });

    test('DEFECT 3: requires_consent sends scripts: true although no script is listed', async () => {
        const recorder = await cplugSheet();
        (document.querySelector('.cplugfacts input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]?.consent).toEqual({ body_sha: 'sha-c', digest: 'dg-c', scripts: true });
    });

    test('END TO END: zero scripts, text shown, accepted, the update carries sha plus scripts, success', async () => {
        const recorder = await cplugSheet();
        const onChange = vi.fn();
        expect(recorder.updates).toEqual([{ expected_revision: 4 }]);
        expect(document.querySelectorAll('.confirm__line')).toHaveLength(0);
        (document.querySelector('.cplugfacts input') as HTMLInputElement).click();
        await settle();
        modalConfirm().click();
        await settle();
        expect(recorder.updates[1]).toEqual({
            expected_revision: 4,
            consent: { body_sha: 'sha-c', digest: 'dg-c', scripts: true },
        });
        expect(document.querySelector('.modal-overlay')).toBeNull();
        expect(document.querySelector('.acts__refusal')).toBeNull();
        void onChange;
    });
});
