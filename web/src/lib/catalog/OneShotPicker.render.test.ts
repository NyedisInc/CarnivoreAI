/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { mount, unmount } from 'svelte';

import OneShotPicker from './OneShotPicker.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CatalogHost } from './catalog';
import type { RunningSessionRow } from '../sessions/types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const ROWS = [
    { name: 'cloude_api', session_id: 'ses_a', label: 'api work', agent_type: 'claude' },
    { name: 'cloude_web', session_id: 'ses_b', label: 'web work', agent_family: 'codex' },
    { name: 'cloude_shell', session_id: 'ses_c', label: 'just a shell' },
] as RunningSessionRow[];

function hostFor(answer: () => Promise<unknown>, rows: RunningSessionRow[] = ROWS): CatalogHost {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    return {
        listItems: refuse,
        refreshIndex: refuse,
        listInstalled: refuse,
        previewInstall: refuse,
        install: refuse,
        uninstall: refuse,
        item: refuse,
        patchInstalled: refuse,
        applyUpdate: refuse,
        runningSessions: () => rows,
        oneShot: answer,
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
    } as unknown as CatalogHost;
}

let sheet: Record<string, unknown> | null = null;

async function open(host: CatalogHost, body: string | null = '# tidy'): Promise<void> {
    const target = document.createElement('div');
    document.body.appendChild(target);
    sheet = mount(OneShotPicker, {
        target,
        props: { name: 'tidy', body, host, t, close: vi.fn() } as never,
    }) as never;
    await new Promise((resolve) => setTimeout(resolve, 0));
}

function options(): string[] {
    return [...document.querySelectorAll('.one-shot__select option')]
        .map((node) => (node.textContent ?? '').trim())
        .filter((text) => text !== '');
}

function paste(): HTMLButtonElement | null {
    return document.querySelector('.modal-btn-primary');
}

async function send(value: string): Promise<void> {
    const select = document.querySelector('.one-shot__select') as HTMLSelectElement;
    select.value = value;
    select.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
    paste()?.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
    if (sheet) unmount(sheet as never);
    sheet = null;
    document.body.innerHTML = '';
});

describe('which panes are offered', () => {
    test('only the ones carrying a recorded agent', async () => {
        await open(hostFor(() => Promise.resolve({})));
        expect(options()).toEqual(['api work (claude)', 'web work (codex)']);
    });

    test('with no eligible pane it says so and offers no control', async () => {
        await open(hostFor(() => Promise.resolve({}), [ROWS[2] as RunningSessionRow]));
        expect(document.body.textContent).toContain(i18n.t('skill.oneshot.none'));
        expect(document.querySelector('.one-shot__select')).toBeNull();
        expect(paste()?.disabled).toBe(true);
    });

    test('with no text to send it says THAT instead, which is a different thing', async () => {
        await open(hostFor(() => Promise.resolve({})), null);
        expect(document.body.textContent).toContain(i18n.t('skill.oneshot.body_absent'));
        expect(document.body.textContent).not.toContain(i18n.t('skill.oneshot.none'));
    });

    test('it says plainly that it installs nothing', async () => {
        await open(hostFor(() => Promise.resolve({})));
        expect(document.body.textContent).toContain(i18n.t('skill.oneshot.detail'));
    });
});

describe('what the server measured', () => {
    test('the bytes, the stripped characters and the one enter are each said', async () => {
        await open(
            hostFor(() =>
                Promise.resolve({ pasted_bytes: 120, stripped_count: 3, submitted: true }),
            ),
        );
        await send('ses_a');
        const report = document.querySelector('.one-shot__report');
        expect(report?.textContent).toContain(i18n.t('skill.oneshot.pasted', { count: 120 }));
        expect(report?.textContent).toContain(i18n.t('skill.oneshot.stripped', { count: 3 }));
        expect(report?.textContent).toContain(i18n.t('skill.oneshot.submitted'));
    });

    test('a paste that landed UNSENT is a real outcome, not a failure', async () => {
        await open(hostFor(() => Promise.resolve({ pasted_bytes: 9, submitted: false })));
        await send('ses_a');
        expect(document.querySelector('.one-shot__report')?.textContent).toContain(
            i18n.t('skill.oneshot.not_submitted'),
        );
        expect(document.querySelector('.one-shot__refusal')).toBeNull();
    });

    test('the control is gone once it has been sent, so a double press cannot repeat it', async () => {
        await open(hostFor(() => Promise.resolve({ pasted_bytes: 9, submitted: true })));
        await send('ses_a');
        expect(paste()).toBeNull();
    });
});

describe('every refusal gets its own sentence', () => {
    const CODES = [
        'pane_not_an_agent',
        'pane_dialog_open',
        'paste_not_settled',
        'paste_not_submitted',
        'body_has_escape',
        'body_too_large',
        'body_empty',
        'body_not_utf8',
    ];

    for (const code of CODES) {
        test(`${code} renders its own sentence and no other`, async () => {
            await open(hostFor(() => Promise.reject({ body: { code } } as never)));
            await send('ses_a');
            const said = document.querySelector('.one-shot__refusal')?.textContent ?? '';
            expect(said).toBe(i18n.t(`skill.refused.${code}`));
            expect(said).not.toBe(i18n.t('skill.refused.unknown'));
        });
    }

    test('a route this server does not carry is NOT a refusal about the skill', async () => {
        const gone = Object.assign(new Error('HTTP 404'), { status: 404, body: {} });
        await open(hostFor(() => Promise.reject(gone)));
        await send('ses_a');
        expect(document.querySelector('.one-shot__refusal')?.textContent).toBe(
            i18n.t('skill.refused.unsupported'),
        );
    });

    test('a code from a newer server is REPORTED, carrying the code', async () => {
        await open(hostFor(() => Promise.reject({ body: { code: 'brand_new' } } as never)));
        await send('ses_a');
        expect(document.querySelector('.one-shot__refusal')?.textContent).toContain('brand_new');
    });
});
