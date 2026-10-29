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

const LONG = 'Return the current time. ' + 'Reads the clock and nothing else. '.repeat(20);
const CPLUG: InstallPreview = {
    body: '{"id":"clock"}',
    files: [{ path: 'cplug.json', size: 20 }],
    publisher: 'acme',
    version: '1.0.0',
    digest: 'abc123def456',
    digest_prefix: 'abc123',
    body_sha: 'sha-of-the-manifest',
    total_bytes: 20,
    requires_consent: true,
    cplug_facts: {
        id: 'clock', name: 'Clock', description: 'tells the time', version: '1.0.0', entry: 'main.py', files: 3, bytes: 643,
        permissions: [
            { name: 'sessions.message', risk: 'high', reason: 'sends a message to a session' },
            { name: 'notify', risk: 'low', reason: 'tells you when the time is up' },
        ],
        tools: [{ name: 'clock_now', gate: 'read', description: LONG, input_schema: { type: 'object' } }],
        network_hosts: [{ host: 'api.example.com', reason: 'fetches the zone table', methods: ['GET'], paths: ['/zones'], secret: 'KEY' }],
        lan_hosts: [],
        secrets: [{ name: 'KEY', label: 'api key', hosts: ['api.example.com'] }],
    },
    cplug_facts_sha: 'facts-sha-1',
};

const installs: InstallRequest[] = [];
let sheet: Record<string, unknown> | null = null;

async function open(preview: InstallPreview): Promise<void> {
    const refuse = () => Promise.reject(new Error('the test never calls this'));
    const host = {
        previewInstall: () => Promise.resolve(preview),
        install: (request: InstallRequest) => {
            installs.push(request);
            return Promise.resolve({ install_id: 'i1' });
        },
        listProjects: () => Promise.resolve([]),
        currentProjectPath: () => Promise.resolve(null),
        listItems: refuse,
    } as unknown as CatalogHost;
    const target = document.createElement('div');
    document.body.appendChild(target);
    sheet = mount(InstallSheet, {
        target,
        props: { card: cardView({ id: 'acme/clock', name: 'clock', kind: 'cplug' }, false), host, t, close: vi.fn() } as never,
    }) as never;
    await new Promise((resolve) => setTimeout(resolve, 0));
}

const confirm = () => document.querySelector('.modal-btn-primary') as HTMLButtonElement;
const ticks = () => [...document.querySelectorAll<HTMLInputElement>('.cplugfacts__accept input')];
async function tick(box: HTMLInputElement): Promise<void> {
    box.checked = !box.checked;
    box.dispatchEvent(new Event('change', { bubbles: true }));
    await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
    if (sheet) unmount(sheet as never);
    sheet = null;
    installs.length = 0;
    document.body.innerHTML = '';
});

describe('the cplug consent sheet', () => {
    test('lists permissions, the full tool text, hosts, secrets and says install does not enable', async () => {
        await open(CPLUG);
        const text = document.querySelector('.cplugfacts')!.textContent!;
        expect(text).toContain('sessions.message');
        expect(text).toContain('sends a message to a session');
        expect(text).toContain(LONG);
        expect(text).toContain('api.example.com');
        expect(text).toContain('sent only to api.example.com');
        expect(text).toContain('installing does not turn it on');
    });

    test('the install stays disabled until the tick, and the request carries the facts sha', async () => {
        await open(CPLUG);
        expect(ticks()).toHaveLength(1);
        expect(confirm().disabled).toBe(true);
        await tick(ticks()[0]!);
        expect(confirm().disabled).toBe(false);
        confirm().click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(installs[0]!.consent).toMatchObject({
            digest: 'abc123def456', body_sha: 'sha-of-the-manifest', scripts: true,
            cplug_accepted: true, cplug_facts_sha: 'facts-sha-1',
        });
    });

    test('a preview with no facts can never be confirmed', async () => {
        await open({ ...CPLUG, cplug_facts: null, cplug_facts_sha: null });
        await tick(ticks()[0]!);
        expect(confirm().disabled).toBe(true);
    });
});
