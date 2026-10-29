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

const MOD: InstallPreview = {
    body: '{"name":"working-on"}',
    files: [{ path: '.claude-plugin/plugin.json', size: 20 }],
    publisher: 'alex',
    version: '0.1.0',
    digest: 'abc123def456',
    digest_prefix: 'abc123',
    body_sha: 'sha-of-the-manifest',
    total_bytes: 20,
    requires_consent: true,
    mod_report: {
        claude_version: '2.1.295 (Claude Code)',
        hooks: [{ module: './register.ts', events: ['session.start', 'turn.complete'] }],
        calls: [{ module: './register.ts', calls: ['$.state.get', '$.model.complete (via refresh)'] }],
        gating: [{ module: './register.ts', pattern: 'classic.PreToolUse', hook: 'handler', has_catch: false }],
        warnings: [],
        spends_plan_usage: true,
        notes_raw: ['./register.ts: gating hook without .catch'],
    },
    mod_report_sha: 'report-sha-1',
    mod_flagged_ack_needed: true,
    mod_settings_groups: ['.claude +4 linked'],
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
        props: { card: cardView({ id: 'alex/working-on', name: 'working-on', kind: 'mod' }, false), host, t, close: vi.fn() } as never,
    }) as never;
    await new Promise((resolve) => setTimeout(resolve, 0));
}

const confirm = () => document.querySelector('.modal-btn-primary') as HTMLButtonElement;
const ticks = () => [...document.querySelectorAll<HTMLInputElement>('.modfacts__accept input')];
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

describe('the mod consent sheet', () => {
    test('lists hooks, calls, the usage warning and the unsandboxed warning', async () => {
        await open(MOD);
        const text = document.querySelector('.modfacts')!.textContent!;
        expect(text).toContain('mods are not sandboxed');
        expect(text).toContain('session.start');
        expect(text).toContain('$.model.complete (via refresh)');
        expect(text).toContain('spends your plan usage');
        expect(text).toContain('no catch');
        expect(text).toContain('registers in 1 claude settings files (.claude +4 linked)');
    });

    test('a flagged or unreviewed mod needs both ticks, and the request carries the report sha', async () => {
        await open(MOD);
        expect(ticks()).toHaveLength(2);
        expect(confirm().disabled).toBe(true);
        await tick(ticks()[0]);
        expect(confirm().disabled).toBe(true);
        await tick(ticks()[1]);
        expect(confirm().disabled).toBe(false);
        confirm().click();
        await new Promise((resolve) => setTimeout(resolve, 0));
        expect(installs[0].consent).toMatchObject({
            digest: 'abc123def456', body_sha: 'sha-of-the-manifest',
            mod_trust: true, mod_flagged_ack: true, mod_report_sha: 'report-sha-1',
        });
    });

    test('a clean review shows one tick and that tick unlocks the install', async () => {
        await open({ ...MOD, mod_flagged_ack_needed: false });
        expect(ticks()).toHaveLength(1);
        expect(confirm().disabled).toBe(true);
        await tick(ticks()[0]);
        expect(confirm().disabled).toBe(false);
    });

    test('a preview with no report can never be confirmed', async () => {
        await open({ ...MOD, mod_report: null, mod_report_sha: null });
        await tick(ticks()[0]);
        await tick(ticks()[1]);
        expect(confirm().disabled).toBe(true);
    });
});
