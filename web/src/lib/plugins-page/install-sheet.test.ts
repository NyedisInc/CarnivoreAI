/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import { ApiError } from '../../opscenter/api/auth.svelte';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { CardView } from '../catalog/card';
import type { CatalogHost } from '../catalog/catalog';
import type { InstallPreview, InstalledItem } from '../catalog/types';
import type { GithubPreviewResponse } from '../plugins/store.svelte';
import type { Translate } from '../sessions/types';
import { toCplugItem, type CplugItem, type CplugRow, type CplugSheet } from './cplugs-adapter';
import type { InstallSheetStore } from './install-sheet-model';
import PluginInstallSheet from './PluginInstallSheet.svelte';

const TEST_STRINGS: Record<string, string> = {
    'plugins.page.github.source_label': 'github repository',
    'plugins.page.github.source_placeholder': 'owner/repo[@ref] or https://github.com/owner/repo',
    'plugins.page.github.source_help': 'enter a public github owner/repo or repository url',
    'plugins.page.github.advanced': 'branch, tag & subfolder',
    'plugins.page.github.ref_label': 'ref (optional)',
    'plugins.page.github.ref_placeholder': 'main, v1.0.0, or commit sha',
    'plugins.page.github.subdir_label': 'subfolder (optional)',
    'plugins.page.github.subdir_placeholder': 'packages/my-plugin',
    'plugins.page.github.preview': 'preview',
    'plugins.page.github.previewing': 'previewing...',
    'plugins.page.install_sheet.title_github': 'install plugin from github',
    'plugins.page.install_sheet.title_named': 'install {name}',
    'plugins.page.install_sheet.title_enable': 'enable {name}',
    'plugins.page.install_sheet.unverified_badge': 'unverified github repo',
    'plugins.page.install_sheet.unverified_banner': 'this code comes directly from an unverified github repository.',
    'plugins.page.install_sheet.summary_version': 'version {version}',
    'plugins.page.install_sheet.summary_commit': 'commit {commit}',
    'plugins.page.install_sheet.summary_publisher': 'by {publisher}',
    'plugins.page.install_sheet.scope_legend': 'install scope',
    'plugins.page.install_sheet.scope_global': 'global',
    'plugins.page.install_sheet.scope_global_hint': 'available across all projects',
    'plugins.page.install_sheet.scope_project': 'project',
    'plugins.page.install_sheet.scope_project_hint': 'installed only in the selected project',
    'plugins.page.install_sheet.project_label': 'project',
    'plugins.page.install_sheet.project_placeholder': 'pick a project',
    'plugins.page.install_sheet.project_none': 'no registered projects available',
    'plugins.page.install_sheet.cap_heading': 'capabilities',
    'plugins.page.install_sheet.cap_none': 'declares no host permissions',
    'plugins.page.install_sheet.cap_low_title': 'low risk permissions',
    'plugins.page.install_sheet.cap_low_tag': 'auto-included',
    'plugins.page.install_sheet.cap_low_summary': '{count} low-risk permissions included automatically',
    'plugins.page.install_sheet.cap_medium_title': 'medium risk permissions',
    'plugins.page.install_sheet.cap_high_title': 'high risk permissions',
    'plugins.page.install_sheet.cap_never_title': 'blocked permissions',
    'plugins.page.install_sheet.cap_never_note': 'this item asks for a forbidden permission and cannot be installed.',
    'plugins.page.install_sheet.cap_granted': 'granted',
    'plugins.page.install_sheet.cap_tick_aria': 'approve {name}',
    'plugins.page.install_sheet.tools_hosts_fold': 'tools & network hosts',
    'plugins.page.install_sheet.tools_heading': 'declared tools',
    'plugins.page.install_sheet.hosts_heading': 'network & lan hosts',
    'plugins.page.install_sheet.tools_hosts_empty': 'no tools or network hosts declared',
    'plugins.page.install_sheet.secrets_heading': 'secrets (stored in keychain)',
    'plugins.page.install_sheet.secret_hosts': 'sent only to: {hosts}',
    'plugins.page.install_sheet.secret_hosts_none': 'sent only to: declared plugin hosts',
    'plugins.page.install_sheet.secret_present': 'saved',
    'plugins.page.install_sheet.secret_needs_reentry': 'needs re-entry',
    'plugins.page.install_sheet.runtime_label': 'activate sandboxed plugin runtime',
    'plugins.page.install_sheet.runtime_hint': 'starts the isolated plugin runtime',
    'plugins.page.install_sheet.loading_preview': 'loading manifest preview...',
    'plugins.page.install_sheet.cta_cancel': 'cancel',
    'plugins.page.install_sheet.cta_install_disabled': 'install disabled',
    'plugins.page.install_sheet.cta_install_enable': 'install & enable',
    'plugins.page.install_sheet.cta_installing': 'installing...',
    'plugins.page.install_sheet.error.safe_mode_forced': 'safe mode is forced by environment configuration, so the plugin runtime cannot be activated.',
    'plugins.page.install_sheet.error.catalog_id_hijack': 'this repository claims a reserved built-in or warez verified id and was refused.',
    'plugins.page.install_sheet.error.name_taken': 'a different plugin with this name is already installed.',
    'plugins.page.install_sheet.error.tick_missing': 'tick every medium and high risk permission before continuing.',
    'plugins.page.install_sheet.error.secret_invalid': 'one or more secret values are invalid or could not be stored in keychain.',
    'plugins.page.install_sheet.error.git_failed': 'could not clone or verify that github repository.',
    'plugins.page.install_sheet.error.consent_stale': 'the manifest changed since preview; run preview again.',
    'plugins.page.install_sheet.error.grant_never': 'forbidden permission cannot be granted.',
    'plugins.page.install_sheet.error.scope_unsupported': 'this item only supports global scope.',
    'plugins.page.permission.root_exec': 'execute as root',
};

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => {
    const template = TEST_STRINGS[key];
    if (!template) return en.t(key, params);
    return template.replace(/\{(\w+)\}/g, (_, k) => String(params?.[k] ?? ''));
};

let mounted: Record<string, unknown> | null = null;

afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 4; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

function setInputValue(input: HTMLInputElement, val: string): void {
    input.value = val;
    input.dispatchEvent(new Event('input', { bubbles: true }));
    flushSync();
}

function ghCplugPreview(overrides: Partial<GithubPreviewResponse> = {}): GithubPreviewResponse {
    return {
        id: 'gh-clock',
        item_id: 'github/gh-clock',
        name: 'GH Clock',
        description: 'Clock from GitHub',
        version: '0.2.0',
        kind: 'cplug',
        trust_tier: 'unverified_github',
        trust_badge: 'Unverified GitHub Repo',
        unverified: true,
        code_sha256: 'sha-code-1',
        permissions: [
            { name: 'sessions.read', risk: 'low', reason: 'read session list', granted: false, needs_tick: false },
            { name: 'network_hosts:api.github.com', risk: 'medium', reason: 'sync releases', granted: false, needs_tick: true },
            { name: 'sessions.message', risk: 'high', reason: 'post alert message', granted: false, needs_tick: true },
        ],
        warnings: [{ code: 'sends_transcripts', reads: 'sessions.read', host: 'api.github.com' }],
        consent_sheet: {
            digest: 'sha-code-1',
            body_sha: 'body-sha-1',
            grants_sha: 'grants-sha-1',
        },
        secrets: [{ name: 'API_TOKEN', label: 'GitHub Token', hosts: ['api.github.com'] }],
        scope: 'global',
        supported_scopes: ['global'],
        runtime_active: false,
        source: { url: 'https://github.com/acme/clock.git', ref: 'main', commit: '0123456789abcdef', subdir: '' },
        tools: [{ name: 'clock_now', gate: 'sessions.read', description: 'return current time', input_schema: { type: 'object' } }],
        network_hosts: [{ host: 'api.github.com', methods: ['GET'], paths: ['/zen'], reason: 'check api' }],
        ...overrides,
    };
}

function makeStore(overrides: Partial<InstallSheetStore> = {}): InstallSheetStore {
    return {
        previewGithub: vi.fn(async () => ghCplugPreview()),
        installGithub: vi.fn(async () => ({
            id: 'gh-clock',
            kind: 'cplug',
            trust_tier: 'unverified_github',
            trust_badge: 'Unverified GitHub Repo',
            unverified: true,
            code_sha256: 'sha-code-1',
            scope: 'global' as const,
            enabled: true,
            runtime_active: true,
        })),
        updatePlugin: vi.fn(async () => ({ id: 'gh-clock', enabled: true, state: 'active' }) as CplugRow),
        refresh: vi.fn(async () => true),
        ...overrides,
    };
}

describe('PluginInstallSheet — github mode', () => {
    test('previews owner/repo, displays Unverified GitHub Repo banner, groups risks, enters masked secrets, activates runtime, and sends consent on both Install & Enable and Install Disabled', async () => {
        const store = makeStore();
        const onDone = vi.fn();
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'github',
                t,
                store,
                onClose: vi.fn(),
                onDone,
            },
        });
        await settle();

        expect(target.querySelector('[data-install-scope]')).toBeNull();

        target.querySelector<HTMLButtonElement>('.oc-fold__toggle')!.click();
        await settle();
        setInputValue(target.querySelector<HTMLInputElement>('[data-github-source]')!, 'acme/clock');
        setInputValue(target.querySelector<HTMLInputElement>('[data-github-ref]')!, 'v0.2.0');
        setInputValue(target.querySelector<HTMLInputElement>('[data-github-subdir]')!, 'pkg');

        target.querySelector<HTMLButtonElement>('[data-github-preview]')!.click();
        await settle();

        expect(store.previewGithub).toHaveBeenCalledWith({
            source: 'acme/clock',
            ref: 'v0.2.0',
            subdir: 'pkg',
        });

        // Unverified GitHub Repo
        const banner = target.querySelector('[data-unverified-banner]');
        expect(banner?.textContent).toContain('Unverified GitHub Repo');

        expect(target.querySelector('[data-install-scope]')).toBeNull();

        const lowGroup = target.querySelector('[data-cap-group="low"]');
        expect(lowGroup?.querySelector('input[type="checkbox"]')).toBeNull();
        expect(lowGroup?.textContent).toContain('1 low-risk permissions included automatically');

        const medTick = target.querySelector<HTMLInputElement>('[data-cap-tick="network_hosts:api.github.com"]')!;
        const highTick = target.querySelector<HTMLInputElement>('[data-cap-tick="sessions.message"]')!;
        expect(medTick.checked).toBe(false);
        expect(highTick.checked).toBe(false);

        expect(target.querySelector('[data-cap-warning]')?.textContent).toBeTruthy();

        const folds = Array.from(target.querySelectorAll<HTMLButtonElement>('.oc-fold__toggle'));
        folds[1]!.click();
        await settle();
        expect(target.querySelector('[data-cap-tool="clock_now"]')?.textContent).toContain('return current time');
        expect(target.querySelector('[data-cap-host="api.github.com"]')?.textContent).toContain('GET');

        const secInput = target.querySelector<HTMLInputElement>('[data-secret-input="API_TOKEN"]')!;
        expect(secInput.type).toBe('password');
        expect(target.querySelector('[data-secret-row="API_TOKEN"]')?.textContent).toContain('sent only to: api.github.com');
        setInputValue(secInput, 'test-token-val');

        const rtCheck = target.querySelector<HTMLInputElement>('[data-runtime-checkbox]')!;
        expect(rtCheck.checked).toBe(true);

        const enableBtn = target.querySelector<HTMLButtonElement>('[data-install-enable]')!;
        const disabledBtn = target.querySelector<HTMLButtonElement>('[data-install-disabled]')!;
        expect(enableBtn.disabled).toBe(true);
        expect(disabledBtn.disabled).toBe(true);

        medTick.click();
        await settle();
        expect(enableBtn.disabled).toBe(true);

        highTick.click();
        await settle();
        expect(enableBtn.disabled).toBe(false);
        expect(disabledBtn.disabled).toBe(false);

        disabledBtn.click();
        await settle();
        expect(store.installGithub).toHaveBeenLastCalledWith({
            source: 'acme/clock',
            ref: 'v0.2.0',
            subdir: 'pkg',
            enable: false,
            activate_runtime: false,
            secrets: { API_TOKEN: 'test-token-val' },
            consent: {
                digest: 'sha-code-1',
                body_sha: 'body-sha-1',
                grants_sha: 'grants-sha-1',
                ticks: ['network_hosts:api.github.com', 'sessions.message'],
            },
        });

        enableBtn.click();
        await settle();
        expect(store.installGithub).toHaveBeenLastCalledWith({
            source: 'acme/clock',
            ref: 'v0.2.0',
            subdir: 'pkg',
            enable: true,
            activate_runtime: true,
            secrets: { API_TOKEN: 'test-token-val' },
            consent: {
                digest: 'sha-code-1',
                body_sha: 'body-sha-1',
                grants_sha: 'grants-sha-1',
                ticks: ['network_hosts:api.github.com', 'sessions.message'],
            },
        });
        expect(onDone).toHaveBeenCalledWith({ id: 'gh-clock', enabled: true });
    });

    test('hard-blocks install when any permission has risk "never"', async () => {
        const store = makeStore({
            previewGithub: vi.fn(async () =>
                ghCplugPreview({
                    permissions: [{ name: 'root.exec', risk: 'never', reason: 'forbidden', granted: false }],
                }),
            ),
        });
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: { open: true, mode: 'github', t, store, onClose: vi.fn(), onDone: vi.fn() },
        });
        await settle();

        setInputValue(target.querySelector<HTMLInputElement>('[data-github-source]')!, 'acme/evil');
        target.querySelector<HTMLButtonElement>('[data-github-preview]')!.click();
        await settle();

        expect(target.querySelector('[data-cap-never-blocked]')).not.toBeNull();
        expect(target.querySelector<HTMLButtonElement>('[data-install-enable]')!.disabled).toBe(true);
        expect(target.querySelector<HTMLButtonElement>('[data-install-disabled]')!.disabled).toBe(true);
    });

    test('shows Global vs Project scope picker ONLY for agent-plugin and passes scope + project_path', async () => {
        const store = makeStore({
            previewGithub: vi.fn(async () => ({
                id: 'gh-agent-mod',
                name: 'Agent Mod',
                version: '1.0.0',
                kind: 'agent-plugin',
                trust_tier: 'unverified_github',
                trust_badge: 'Unverified GitHub Repo',
                unverified: true,
                permissions: [],
                consent_sheet: { digest: 'd1', body_sha: 'b1' },
                secrets: [],
                scope: 'global' as const,
                supported_scopes: ['global', 'project'] as const,
                runtime_active: true,
                source: { url: 'https://github.com/acme/agent.git', commit: 'abcdef123456', subdir: '' },
            })),
            installGithub: vi.fn(async () => ({
                id: 'gh-agent-mod',
                kind: 'agent-plugin',
                trust_tier: 'unverified_github',
                trust_badge: 'Unverified GitHub Repo',
                unverified: true,
                code_sha256: 'd1',
                scope: 'project' as const,
                project_path: '/proj/alpha',
                enabled: true,
                runtime_active: true,
            })),
        });
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'github',
                t,
                store,
                projects: [{ path: '/proj/alpha', name: 'Alpha' }],
                onClose: vi.fn(),
                onDone: vi.fn(),
            },
        });
        await settle();

        setInputValue(target.querySelector<HTMLInputElement>('[data-github-source]')!, 'acme/agent');
        target.querySelector<HTMLButtonElement>('[data-github-preview]')!.click();
        await settle();

        expect(target.querySelector('[data-install-scope]')).not.toBeNull();
        expect(target.querySelector('[data-runtime-toggle]')).toBeNull();

        const projectRadio = target.querySelector<HTMLInputElement>('input[type="radio"][value="project"]')!;
        projectRadio.click();
        await settle();

        const enableBtn = target.querySelector<HTMLButtonElement>('[data-install-enable]')!;
        expect(enableBtn.disabled).toBe(true);

        const sel = target.querySelector<HTMLSelectElement>('[data-install-project]')!;
        sel.value = '/proj/alpha';
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();
        expect(enableBtn.disabled).toBe(false);

        enableBtn.click();
        await settle();

        expect(store.installGithub).toHaveBeenCalledWith({
            source: 'acme/agent',
            scope: 'project',
            project_path: '/proj/alpha',
            enable: true,
            activate_runtime: false,
            consent: { digest: 'd1', body_sha: 'b1' },
        });
    });

    test.each([
        ['safe_mode_forced', 409, 'safe mode is forced by environment configuration, so the plugin runtime cannot be activated.'],
        ['catalog_id_hijack', 409, 'this repository claims a reserved built-in or warez verified id and was refused.'],
        ['name_taken', 409, 'a different plugin with this name is already installed.'],
        ['tick_missing', 422, 'tick every medium and high risk permission before continuing.'],
        ['secret_invalid', 422, 'one or more secret values are invalid or could not be stored in keychain.'],
        ['git_failed', 502, 'could not clone or verify that github repository.'],
    ])('maps backend %s (%i) to plain-English error copy', async (code, status, expectedText) => {
        const store = makeStore({
            previewGithub: vi.fn(async () => {
                throw new ApiError(`HTTP ${status}`, status, code, { detail: { code, detail: 'raw' } });
            }),
        });
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: { open: true, mode: 'github', t, store, onClose: vi.fn(), onDone: vi.fn() },
        });
        await settle();

        setInputValue(target.querySelector<HTMLInputElement>('[data-github-source]')!, 'acme/demo');
        target.querySelector<HTMLButtonElement>('[data-github-preview]')!.click();
        await settle();

        expect(target.textContent).toContain(expectedText);
    });
});

describe('PluginInstallSheet — catalog & enable modes', () => {
    test('catalog cplug Install & Enable chains host.install -> GET /sheet -> store.updatePlugin without showing scope picker', async () => {
        const store = makeStore();
        const preview: InstallPreview = {
            digest: 'cat-digest',
            body_sha: 'cat-body',
            plan_token: 'plan-1',
            cplug_facts_sha: 'facts-sha-1',
            cplug_facts: {
                id: 'warez-clock',
                name: 'Warez Clock',
                description: 'Signed clock',
                version: '1.0.0',
                entry: 'main.py',
                files: 3,
                bytes: 1024,
                permissions: [{ name: 'sessions.read', risk: 'low', reason: 'read' }, { name: 'notify', risk: 'medium', reason: 'alert' }],
                tools: [],
                network_hosts: [],
                lan_hosts: [],
                secrets: [{ name: 'HOOK_KEY', label: 'Hook Key', hosts: ['hooks.example.com'] }],
            },
        };
        const host = {
            previewInstall: vi.fn(async () => preview),
            install: vi.fn(async () => ({ install_id: 'inst-1', name: 'warez-clock' }) as InstalledItem),
            listProjects: vi.fn(async () => []),
        } as unknown as CatalogHost;
        const card = {
            id: 'pub/warez-clock',
            name: 'warez-clock',
            headline: 'Warez Clock',
            version: '1.0.0',
            isCplug: true,
            isPlugin: false,
            untrusted: false,
        } as unknown as CardView;
        const loadSheet = vi.fn(async (): Promise<CplugSheet> => ({
            digest: 'sheet-d',
            body_sha: 'sheet-b',
            grants_sha: 'sheet-g',
            permissions: [
                { name: 'sessions.read', risk: 'low', granted: false },
                { name: 'notify', risk: 'medium', granted: false },
            ],
        }));
        const onDone = vi.fn();

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'catalog',
                card,
                host,
                runtimeActive: false,
                store,
                loadSheet,
                t,
                onClose: vi.fn(),
                onDone,
            },
        });
        await settle();

        expect(target.querySelector('[data-install-scope]')).toBeNull();
        target.querySelector<HTMLInputElement>('[data-cap-tick="notify"]')!.click();
        setInputValue(target.querySelector<HTMLInputElement>('[data-secret-input="HOOK_KEY"]')!, 'hook-secret');
        await settle();

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();

        expect(host.install).toHaveBeenCalledTimes(1);
        expect(loadSheet).toHaveBeenCalledWith('warez-clock');
        expect(store.updatePlugin).toHaveBeenCalledWith('warez-clock', {
            enabled: true,
            grants: { app: ['sessions.read', 'notify'] },
            consent: {
                digest: 'sheet-d',
                body_sha: 'sheet-b',
                grants_sha: 'sheet-g',
                ticks: ['notify'],
            },
            activate_runtime: true,
            secrets: { HOOK_KEY: 'hook-secret' },
        });
        expect(onDone).toHaveBeenCalledWith({ id: 'warez-clock', enabled: true });
    });

    test('enable mode omits Install Disabled, shows secretsStatus badges, and enables via updatePlugin', async () => {
        const store = makeStore();
        const item = {
            id: 'cplug:gh-clock',
            kind: 'cplug',
            cplugId: 'gh-clock',
            name: 'GH Clock',
            version: '0.2.0',
            state: 'disabled',
            enabled: false,
            consentRequired: true,
            thirdParty: true,
            unverified: true,
            trustTier: 'unverified_github',
            trustBadge: 'Unverified GitHub Repo',
            permissions: [
                { name: 'sessions.read', label: 'read sessions', risk: 'low', reason: 'read', granted: true },
                { name: 'notify', label: 'send alerts', risk: 'medium', reason: 'alert', granted: false },
            ],
            warnings: [],
            secretsStatus: { API_TOKEN: { present: false, needs_reentry: true } },
            tools: [],
            missing: ['notify'],
            blockedBy: [],
            asks: [],
            settings: {},
            settingsSchema: null,
            deps: { needs: [], neededBy: [], enabledDependents: [] },
            tier: 'catalog',
            surfaces: {},
            heldReason: 'third_party_off',
            storageBytes: 0,
            changedFiles: [],
            publisher: 'github',
            marks: [],
            tags: [],
            brief: null,
            meta: null,
            icon: 'plug',
            byline: null,
        } as unknown as CplugItem;
        const loadSheet = vi.fn(async (): Promise<CplugSheet> => ({
            digest: 'en-d',
            body_sha: 'en-b',
            grants_sha: 'en-g',
            permissions: [
                { name: 'sessions.read', risk: 'low', granted: true },
                { name: 'notify', risk: 'medium', granted: false },
            ],
        }));

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'enable',
                item,
                store,
                loadSheet,
                t,
                onClose: vi.fn(),
                onDone: vi.fn(),
            },
        });
        await settle();

        expect(target.querySelector('[data-install-disabled]')).toBeNull();
        expect(target.querySelector('[data-secret-status="needs_reentry"]')).not.toBeNull();
        expect(target.querySelector<HTMLInputElement>('[data-runtime-checkbox]')!.checked).toBe(true);

        target.querySelector<HTMLInputElement>('[data-cap-tick="notify"]')!.click();
        setInputValue(target.querySelector<HTMLInputElement>('[data-secret-input="API_TOKEN"]')!, 'reentered-secret');
        await settle();

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();

        expect(store.updatePlugin).toHaveBeenCalledWith('gh-clock', {
            enabled: true,
            grants: { app: ['sessions.read', 'notify'] },
            consent: {
                digest: 'en-d',
                body_sha: 'en-b',
                grants_sha: 'en-g',
                ticks: ['notify'],
            },
            activate_runtime: true,
            secrets: { API_TOKEN: 'reentered-secret' },
        });
    });

    test('catalog agent-plugin shows scope picker and passes scope + project_path to host.install', async () => {
        const store = makeStore();
        const preview: InstallPreview = {
            digest: 'ap-digest',
            body_sha: 'ap-body',
            plan_token: 'ap-plan',
        };
        const host = {
            previewInstall: vi.fn(async () => preview),
            install: vi.fn(async () => ({ install_id: 'ap-inst-1', name: 'agent-pack' }) as InstalledItem),
            listProjects: vi.fn(async () => [{ path: '/proj/beta', name: 'Beta' }]),
        } as unknown as CatalogHost;
        const card = {
            id: 'pub/agent-pack',
            name: 'agent-pack',
            headline: 'Agent Pack',
            version: '1.0.0',
            isCplug: false,
            isPlugin: true,
            untrusted: false,
        } as unknown as CardView;
        const onDone = vi.fn();

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'catalog',
                card,
                host,
                store,
                t,
                onClose: vi.fn(),
                onDone,
            },
        });
        await settle();

        expect(target.querySelector('[data-install-scope]')).not.toBeNull();
        expect(target.querySelector('[data-runtime-toggle]')).toBeNull();

        target.querySelector<HTMLInputElement>('input[type="radio"][value="project"]')!.click();
        await settle();
        const sel = target.querySelector<HTMLSelectElement>('[data-install-project]')!;
        sel.value = '/proj/beta';
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();

        expect(host.install).toHaveBeenCalledWith({
            item_id: 'pub/agent-pack',
            scope: 'project',
            project_path: '/proj/beta',
            plan_token: 'ap-plan',
            consent: { digest: 'ap-digest', body_sha: 'ap-body', scripts: true },
        });
        expect(onDone).toHaveBeenCalledWith({
            id: 'ap-inst-1',
            enabled: true,
            scope: 'project',
            projectPath: '/proj/beta',
        });
    });

    test('BUG-1: catalog cplug uses preview.runtime_active=false without runtimeActive prop and sends activate_runtime=true', async () => {
        const store = makeStore();
        const preview: InstallPreview & { runtime_active: boolean } = {
            digest: 'cat-digest',
            body_sha: 'cat-body',
            plan_token: 'plan-rt',
            cplug_facts_sha: 'facts-rt',
            runtime_active: false,
            cplug_facts: {
                id: 'warez-rt',
                name: 'Warez Runtime',
                description: 'Runtime check',
                version: '1.0.0',
                entry: 'main.py',
                files: 2,
                bytes: 512,
                permissions: [{ name: 'sessions.read', risk: 'low', reason: 'read' }],
                tools: [],
                network_hosts: [],
                lan_hosts: [],
                secrets: [],
            },
        };
        const host = {
            previewInstall: vi.fn(async () => preview),
            install: vi.fn(async () => ({ install_id: 'inst-rt', name: 'warez-rt' }) as InstalledItem),
            listProjects: vi.fn(async () => []),
        } as unknown as CatalogHost;
        const card = {
            id: 'pub/warez-rt',
            name: 'warez-rt',
            headline: 'Warez Runtime',
            version: '1.0.0',
            isCplug: true,
            isPlugin: false,
            untrusted: false,
        } as unknown as CardView;
        const loadSheet = vi.fn(async (): Promise<CplugSheet> => ({
            digest: 'rt-d',
            body_sha: 'rt-b',
            grants_sha: 'rt-g',
            permissions: [{ name: 'sessions.read', risk: 'low', granted: false }],
        }));

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: { open: true, mode: 'catalog', card, host, store, loadSheet, t, onClose: vi.fn(), onDone: vi.fn() },
        });
        await settle();

        const rtCheck = target.querySelector<HTMLInputElement>('[data-runtime-checkbox]');
        expect(rtCheck).not.toBeNull();
        expect(rtCheck!.checked).toBe(true);

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();

        expect(store.updatePlugin).toHaveBeenCalledWith(
            'warez-rt',
            expect.objectContaining({ enabled: true, activate_runtime: true }),
        );
    });

    test('BUG-1: enable mode renders runtime toggle for real cplug_row with runtime_active=false (no synthetic third_party_off)', async () => {
        const store = makeStore();
        const row = {
            id: 'sidecar-rt',
            name: 'Sidecar RT',
            description: 'Held by inactive runtime',
            version: '1.0.0',
            runtime: 'sidecar',
            tier: 'catalog',
            publisher: 'harbor',
            enabled: false,
            state: 'unavailable',
            detail: 'disabled (safe mode)',
            runtime_active: false,
            consent_required: true,
            permissions: { app: ['sessions.read'] },
            grants: { app: [] },
            risks: { 'sessions.read': 'low' },
            needs: ['sessions.read'],
        } as CplugRow & { runtime_active: boolean };
        const item = {
            ...toCplugItem(row, t),
            runtimeActive: false,
        } as CplugItem & { runtimeActive: boolean };
        const loadSheet = vi.fn(async (): Promise<CplugSheet> => ({
            digest: 's-d',
            body_sha: 's-b',
            grants_sha: 's-g',
            permissions: [{ name: 'sessions.read', risk: 'low', granted: false }],
        }));

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: { open: true, mode: 'enable', item, store, loadSheet, t, onClose: vi.fn(), onDone: vi.fn() },
        });
        await settle();

        const rtCheck = target.querySelector<HTMLInputElement>('[data-runtime-checkbox]');
        expect(rtCheck).not.toBeNull();
        expect(rtCheck!.checked).toBe(true);

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();

        expect(store.updatePlugin).toHaveBeenCalledWith(
            'sidecar-rt',
            expect.objectContaining({ enabled: true, activate_runtime: true }),
        );
    });

    test('BUG-2: catalog cplug Install Disabled persists entered secrets via updatePlugin(enabled=false) and surfaces secret_invalid', async () => {
        const updatePlugin = vi
            .fn()
            .mockResolvedValueOnce({ id: 'warez-sec', enabled: false, state: 'disabled' } as CplugRow)
            .mockRejectedValueOnce(new ApiError('HTTP 422', 422, 'secret_invalid', { detail: { code: 'secret_invalid' } }));
        const store = makeStore({ updatePlugin });
        const preview: InstallPreview = {
            digest: 'sec-d',
            body_sha: 'sec-b',
            plan_token: 'sec-plan',
            cplug_facts_sha: 'sec-facts',
            cplug_facts: {
                id: 'warez-sec',
                name: 'Warez Secret',
                description: 'Uses secret',
                version: '1.0.0',
                entry: 'main.py',
                files: 2,
                bytes: 512,
                permissions: [{ name: 'sessions.read', risk: 'low', reason: 'read' }],
                tools: [],
                network_hosts: [],
                lan_hosts: [],
                secrets: [{ name: 'API_KEY', label: 'API Key', hosts: ['api.example.com'] }],
            },
        };
        const host = {
            previewInstall: vi.fn(async () => preview),
            install: vi.fn(async () => ({ install_id: 'inst-sec', name: 'warez-sec' }) as InstalledItem),
            listProjects: vi.fn(async () => []),
        } as unknown as CatalogHost;
        const card = {
            id: 'pub/warez-sec',
            name: 'warez-sec',
            headline: 'Warez Secret',
            version: '1.0.0',
            isCplug: true,
            isPlugin: false,
            untrusted: false,
        } as unknown as CardView;
        const onDone = vi.fn();

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: { open: true, mode: 'catalog', card, host, store, t, onClose: vi.fn(), onDone },
        });
        await settle();

        setInputValue(target.querySelector<HTMLInputElement>('[data-secret-input="API_KEY"]')!, 'sk_live_123');
        target.querySelector<HTMLButtonElement>('[data-install-disabled]')!.click();
        await settle();

        expect(updatePlugin).toHaveBeenNthCalledWith(1, 'warez-sec', {
            enabled: false,
            secrets: { API_KEY: 'sk_live_123' },
        });
        expect(onDone).toHaveBeenCalledTimes(1);

        target.querySelector<HTMLButtonElement>('[data-install-disabled]')!.click();
        await settle();
        expect(target.querySelector('[data-install-error]')?.textContent).toContain(
            'one or more secret values are invalid or could not be stored in keychain.',
        );
        expect(onDone).toHaveBeenCalledTimes(1);
    });

    test('BUG-3: github mode switching from project-scoped agent-plugin to cplug repo resets scope and avoids 409 scope_unsupported trap', async () => {
        const previewGithub = vi.fn(async (req: { source: string; scope?: string }) => {
            if (req.source === 'acme/agent') {
                return {
                    id: 'gh-agent',
                    name: 'Agent Mod',
                    version: '1.0.0',
                    kind: 'agent-plugin',
                    trust_tier: 'unverified_github',
                    trust_badge: 'Unverified GitHub Repo',
                    unverified: true,
                    permissions: [],
                    consent_sheet: { digest: 'd1', body_sha: 'b1' },
                    secrets: [],
                    scope: 'global' as const,
                    supported_scopes: ['global', 'project'] as const,
                    runtime_active: true,
                    source: { url: 'https://github.com/acme/agent.git', commit: 'abcdef12', subdir: '' },
                };
            }
            if (req.scope === 'project') {
                throw new ApiError('HTTP 409', 409, 'scope_unsupported', { detail: { code: 'scope_unsupported' } });
            }
            return ghCplugPreview({ permissions: [], warnings: [], secrets: [] });
        });
        const store = makeStore({ previewGithub });

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'github',
                t,
                store,
                projects: [{ path: '/proj/alpha', name: 'Alpha' }],
                onClose: vi.fn(),
                onDone: vi.fn(),
            },
        });
        await settle();

        setInputValue(target.querySelector<HTMLInputElement>('[data-github-source]')!, 'acme/agent');
        target.querySelector<HTMLButtonElement>('[data-github-preview]')!.click();
        await settle();
        target.querySelector<HTMLInputElement>('input[type="radio"][value="project"]')!.click();
        await settle();
        const sel = target.querySelector<HTMLSelectElement>('[data-install-project]')!;
        sel.value = '/proj/alpha';
        sel.dispatchEvent(new Event('change', { bubbles: true }));
        await settle();

        setInputValue(target.querySelector<HTMLInputElement>('[data-github-source]')!, 'acme/clock');
        target.querySelector<HTMLButtonElement>('[data-github-preview]')!.click();
        await settle();

        expect(target.querySelector('[data-install-summary]')).not.toBeNull();
        expect(target.querySelector('[data-install-scope]')).toBeNull();
        expect(target.textContent).not.toContain('only supports global scope');
    });

    test('BUG-4: initialScope="project" with initialProject pre-selects Project radio and project option on open', async () => {
        const store = makeStore();
        const preview: InstallPreview = {
            digest: 'ap-d',
            body_sha: 'ap-b',
            plan_token: 'ap-p',
        };
        const host = {
            previewInstall: vi.fn(async () => preview),
            install: vi.fn(async () => ({ install_id: 'ap-inst-2', name: 'agent-pack' }) as InstalledItem),
            listProjects: vi.fn(async () => [{ path: '/proj/beta', name: 'Beta' }]),
        } as unknown as CatalogHost;
        const card = {
            id: 'pub/agent-pack',
            name: 'agent-pack',
            headline: 'Agent Pack',
            version: '1.0.0',
            isCplug: false,
            isPlugin: true,
            untrusted: false,
        } as unknown as CardView;
        const onDone = vi.fn();

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: {
                open: true,
                mode: 'catalog',
                card,
                host,
                initialScope: 'project',
                initialProject: '/proj/beta',
                store,
                t,
                onClose: vi.fn(),
                onDone,
            },
        });
        await settle();

        const projectRadio = target.querySelector<HTMLInputElement>('input[type="radio"][value="project"]')!;
        expect(projectRadio.checked).toBe(true);
        const sel = target.querySelector<HTMLSelectElement>('[data-install-project]')!;
        expect(sel.value).toBe('/proj/beta');

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();

        expect(host.install).toHaveBeenCalledWith(
            expect.objectContaining({ scope: 'project', project_path: '/proj/beta' }),
        );
        expect(onDone).toHaveBeenCalledWith({
            id: 'ap-inst-2',
            enabled: true,
            scope: 'project',
            projectPath: '/proj/beta',
        });
    });
});
