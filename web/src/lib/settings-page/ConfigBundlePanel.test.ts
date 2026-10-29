/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import ConfigBundlePanel from './ConfigBundlePanel.svelte';
import { ApiError } from '../../opscenter/api/auth.svelte';
import { setLocale } from '../i18n/index.svelte';
import type { Fetcher, ImportAnswer } from './config-bundle/api';

setLocale('en');

const BUNDLE = { kind: 'carnivore-config-bundle', exported_at: '2026-09-29T10:00:00Z', config: { uploads: { enabled: true } } };

const PREVIEW: ImportAnswer = {
    status: 'preview',
    dry_run: true,
    mode: 'merge',
    changes: [
        { path: 'config.uploads.ttl_seconds', kind: 'changed', before: '5', after: '111' },
        { path: 'pinned_themes.cloude_a', kind: 'added', before: null, after: '"matrix"' },
    ],
    counts: { added: 1, changed: 1, removed: 0 },
    truncated: false,
    stripped: [],
    ignored: [],
    backup: null,
    source: { source_host: 'old-mac', from_other_host: true, app_version: '1.12.1' },
};

interface Call {
    path: string;
    body: Record<string, unknown> | null;
}

function harness(answer: (call: Call) => unknown) {
    const calls: Call[] = [];
    const saved: Array<{ name: string; text: string }> = [];
    const fetcher = (async (path: string, init?: RequestInit) => {
        const call = { path, body: init?.body ? JSON.parse(String(init.body)) : null };
        calls.push(call);
        const out = answer(call);
        if (out instanceof Error) throw out;
        return out;
    }) as unknown as Fetcher;
    const target = document.createElement('div');
    const handle = mount(ConfigBundlePanel, { target, props: { fetcher, save: (name: string, text: string) => saved.push({ name, text }) } });
    flushSync();
    return { target, handle, calls, saved };
}

async function settle(): Promise<void> {
    for (let i = 0; i < 5; i += 1) {
        await Promise.resolve();
        flushSync();
    }
}

async function choose(target: HTMLElement, text: string): Promise<void> {
    const input = target.querySelector<HTMLInputElement>('input[type="file"]')!;
    Object.defineProperty(input, 'files', { value: [{ text: async () => text }], configurable: true });
    input.dispatchEvent(new Event('change', { bubbles: true }));
    await settle();
}

const click = (target: HTMLElement, selector: string): void => {
    target.querySelector<HTMLElement>(selector)!.click();
    flushSync();
};

afterEach(() => {
    document.body.innerHTML = '';
});

describe('export config', () => {
    test('downloads exactly what the server sent, under a dated name, and says it holds no credential', async () => {
        const { target, handle, calls, saved } = harness(() => BUNDLE);
        click(target, '[data-cb="export"]');
        await settle();
        expect(calls.map((c) => c.path)).toEqual(['/config/export']);
        expect(saved).toHaveLength(1);
        expect(saved[0]!.name).toBe('carnivore-config-20260929.json');
        expect(JSON.parse(saved[0]!.text)).toEqual(BUNDLE);
        expect(target.querySelector('[data-cb="note"]')!.textContent).toContain('carnivore-config-20260929.json');
        expect(target.textContent).toContain('credentials are never in it');
        unmount(handle);
    });

    test('a failed export shows the reason and saves nothing', async () => {
        const { target, handle, saved } = harness(() => new ApiError('configuration is missing', 500));
        click(target, '[data-cb="export"]');
        await settle();
        expect(saved).toEqual([]);
        expect(target.querySelector('[data-cb="problem"]')!.textContent).toContain('configuration is missing');
        unmount(handle);
    });
});

describe('import config', () => {
    test('a chosen file is previewed with a dry run, nothing is applied until the confirm', async () => {
        const { target, handle, calls } = harness((call) =>
            call.body?.dry_run === false ? { ...PREVIEW, status: 'applied', dry_run: false } : PREVIEW,
        );
        await choose(target, JSON.stringify(BUNDLE));
        expect(calls).toHaveLength(1);
        expect(calls[0]!.body).toMatchObject({ mode: 'merge', dry_run: true, bundle: BUNDLE });
        const rows = [...target.querySelectorAll('.cb__change')].map((r) => r.getAttribute('data-kind'));
        expect(rows).toEqual(['changed', 'added']);
        expect(target.textContent).toContain('old-mac');
        expect(target.textContent).toContain('config.uploads.ttl_seconds');

        click(target, '[data-cb="apply"]');
        await settle();
        expect(calls).toHaveLength(2);
        expect(calls[1]!.body).toMatchObject({ dry_run: false, mode: 'merge' });
        expect(target.querySelector('[data-cb="preview"]')).toBeNull();
        expect(target.querySelector('[data-cb="note"]')!.textContent).toContain('config.json.bak');
        unmount(handle);
    });

    test('cancel discards the file without a second request', async () => {
        const { target, handle, calls } = harness(() => PREVIEW);
        await choose(target, JSON.stringify(BUNDLE));
        click(target, '[data-cb="cancel"]');
        await settle();
        expect(calls).toHaveLength(1);
        expect(target.querySelector('[data-cb="preview"]')).toBeNull();
        unmount(handle);
    });

    test('switching to replace re-previews with that mode', async () => {
        const { target, handle, calls } = harness(() => PREVIEW);
        await choose(target, JSON.stringify(BUNDLE));
        click(target, '[data-cb-mode="replace"]');
        await settle();
        expect(calls).toHaveLength(2);
        expect(calls[1]!.body).toMatchObject({ mode: 'replace', dry_run: true });
        unmount(handle);
    });

    test('a file that is not json never reaches the server', async () => {
        const { target, handle, calls } = harness(() => PREVIEW);
        await choose(target, 'this is not json');
        expect(calls).toEqual([]);
        expect(target.querySelector('[data-cb="problem"]')!.textContent).toContain('not valid json');
        expect(target.querySelector('[data-cb="preview"]')).toBeNull();
        unmount(handle);
    });

    test('a server refusal is shown with its field lines and offers no apply', async () => {
        const { target, handle } = harness(
            () => new ApiError('x', 422, null, { detail: ['uploads.ttl_seconds: not a number', 'kind: wrong'] }),
        );
        await choose(target, JSON.stringify(BUNDLE));
        expect(target.querySelector('[data-cb="problem"]')!.textContent!.trim()).toBe('uploads.ttl_seconds: not a number; kind: wrong');
        expect(target.querySelector('[data-cb="apply"]')).toBeNull();
        unmount(handle);
    });

    test('an empty preview says nothing would change', async () => {
        const { target, handle } = harness(() => ({ ...PREVIEW, changes: [], counts: { added: 0, changed: 0, removed: 0 } }));
        await choose(target, JSON.stringify(BUNDLE));
        expect(target.querySelector('[data-cb="empty"]')).not.toBeNull();
        expect(target.querySelector('.cb__changes')).toBeNull();
        unmount(handle);
    });
});
