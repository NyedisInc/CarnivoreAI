/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import DetailActions from './DetailActions.svelte';
import CatalogCard from './CatalogCard.svelte';
import DeprecatedMark from './DeprecatedMark.svelte';
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


const DIFF = {
    from_version: '0.9',
    to_version: '1.0',
    unchanged: 2,
    changes: [
        {
            path: 'SKILL.md',
            status: 'changed',
            old_size: 30,
            new_size: 44,
            diff: '--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1 +1 @@\n-old line\n+new line\n',
        },
        { path: 'reference.md', status: 'added', old_size: null, new_size: 8, diff: '+# more\n' },
        { path: 'img/logo.png', status: 'changed', old_size: 5, new_size: 6, diff: null, diff_reason: 'binary' },
    ],
};

describe('the update sheet diff', () => {
    test('lists a changed SKILL.md with its text diff, an added file and a binary file without a diff', async () => {
        const recorder = hostFor({ body: '# new text', body_sha: 'sha-new', diff: DIFF });
        paint(recorder.host);
        await startUpdate();
        const files = [...document.querySelectorAll('[data-diff-file]')];
        expect(files.map((f) => `${f.getAttribute('data-diff-file')}:${f.getAttribute('data-diff-status')}`)).toEqual([
            'SKILL.md:changed',
            'reference.md:added',
            'img/logo.png:changed',
        ]);
        const skillMd = files[0]!;
        expect(skillMd.querySelector('[data-diff-text]')?.textContent).toContain('-old line');
        expect(skillMd.querySelector('.udiff__line--add')?.textContent).toContain('+new line');
        expect(files[2]!.querySelector('[data-diff-text]')).toBeNull();
        expect(files[2]!.querySelector('[data-diff-reason]')?.getAttribute('data-diff-reason')).toBe('binary');
        expect(document.body.textContent).toContain('changes from 0.9 to 1.0');
    });

    test('an update 409 with no diff shows no diff block', async () => {
        const recorder = hostFor({ body: '# new text', body_sha: 'sha-new' });
        paint(recorder.host);
        await startUpdate();
        expect(document.querySelector('.confirm__document')).not.toBeNull();
        expect(document.querySelector('[data-update-diff]')).toBeNull();
    });
});

describe('the deprecated mark', () => {
    const cardProps = (item: Record<string, unknown>) => ({
        card: cardView({ id: 'a/b', name: 'tidy', latest: '1.0', ...item }, false),
        state: { kind: 'idle' },
        t,
        onInstall: vi.fn(),
        onUpdate: vi.fn(),
        onUninstall: vi.fn(),
    });

    test('the card wears the mark for a deprecated item and not for a live one', () => {
        const target = document.createElement('div');
        document.body.appendChild(target);
        panel = mount(CatalogCard, { target, props: cardProps({ deprecated: { superseded_by: 'a/tidy2' } }) as never }) as never;
        const mark = document.querySelector('[data-deprecated-mark]');
        expect(mark?.textContent).toBe('deprecated');
        expect(mark?.hasAttribute('title')).toBe(false);
        unmount(panel as never);
        panel = mount(CatalogCard, { target, props: cardProps({}) as never }) as never;
        expect(document.querySelector('[data-deprecated-mark]')).toBeNull();
    });

    test('the detail note names the replacement item when the index names one', () => {
        const target = document.createElement('div');
        document.body.appendChild(target);
        panel = mount(DeprecatedMark, { target, props: { supersededBy: 'a/tidy2', t } as never }) as never;
        expect(document.querySelector('[data-deprecated-note]')?.textContent).toContain('a/tidy2');
    });
});
