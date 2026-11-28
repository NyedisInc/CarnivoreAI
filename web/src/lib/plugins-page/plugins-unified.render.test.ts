/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import PluginsScreen from './PluginsScreen.svelte';
import { createCatalogPlugins } from './catalog-plugins.svelte';
import { toCplugItem, type CplugRow } from './cplugs-adapter';
import { auth } from '../../opscenter/api/auth.svelte';
import { pluginsStore } from '../plugins/store.svelte';
import type { CatalogHost } from '../catalog/catalog';
import type { InstalledItem } from '../catalog/types';
import type { ManagerAdapter } from '../manager-frame/types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';
import type { Translate } from '../sessions/types';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const en = createI18n({ locale: 'en' }) as { t: Translate };
const t: Translate = (key, params) => en.t(key, params);

const BUILTIN_ROW: CplugRow = {
    id: 'huddle',
    name_key: 'cplug.huddle.name',
    version: '1.0.0',
    tier: 'builtin',
    enabled: true,
    state: 'active',
    permissions: { app: [] },
    grants: { app: [] },
    needs: [],
};

const APP_PLUGIN_ROW: CplugRow = {
    id: 'acme-clock',
    name: 'Acme Clock',
    description: 'Sidecar app plugin',
    version: '1.2.0',
    runtime: 'sidecar',
    tier: 'catalog',
    publisher: 'acme',
    enabled: true,
    state: 'active',
    trust_tier: 'verified',
    watchdog: { pid: 9001, restart_count: 1, rss_bytes: 24 * 1024 * 1024, last_call: 'tick', last_event: 'ok' },
    permissions: { app: [] },
    grants: { app: [] },
    needs: [],
};

const SIDECAR_CONSENT_ROW: CplugRow = {
    id: 'needs-gate',
    name: 'Needs Gate',
    description: 'Needs consent on enable',
    version: '1.0.0',
    runtime: 'sidecar',
    tier: 'catalog',
    publisher: 'harbor',
    enabled: false,
    state: 'disabled',
    consent_required: true,
    permissions: { app: ['notify'] },
    grants: { app: [] },
    needs: [],
};

const AGENT_PLUGIN_ROW: CplugRow = {
    id: 'agent:repo-pulse',
    item_id: 'repo-pulse',
    install_id: 'inst-agent-99',
    kind: 'agent-plugin',
    name: 'Repo Pulse',
    description: 'Agent plugin from GitHub',
    version: '0.4.0',
    tier: 'community',
    publisher: 'octocat',
    enabled: null,
    state: 'active',
    trust_tier: 'unverified_github',
    trust_badge: 'Unverified',
    scope: 'project',
    project_path: '/tmp/repo-pulse',
    git_source: { url: 'https://github.com/octocat/repo-pulse', repo: 'octocat/repo-pulse', ref: 'main', commit: 'deadbeef' },
    permissions: { app: [] },
    grants: { app: [] },
    needs: [],
};

const LOCAL_DEV_ROW: CplugRow = {
    id: 'local-probe',
    name: 'Local Probe',
    description: 'Local dev folder plugin',
    version: '0.1.0',
    runtime: 'sidecar',
    tier: 'local',
    publisher: 'local',
    enabled: false,
    state: 'disabled',
    unverified: true,
    permissions: { app: [] },
    grants: { app: [] },
    needs: [],
};

const LEDGER_AGENT_ROW: InstalledItem = {
    install_id: 'inst-agent-99',
    item_id: 'repo-pulse',
    kind: 'plugin',
    scope: 'project',
    project_path: '/tmp/repo-pulse',
    source_index_url: 'https://github.com/octocat/repo-pulse',
    revision: 1,
};

let mounted: Record<string, unknown> | null = null;
const origFetch = globalThis.fetch;
const origAuthState = auth.state;
const origApi = (window as unknown as { API?: unknown }).API;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    globalThis.fetch = origFetch;
    auth.state = origAuthState;
    (window as unknown as { API?: unknown }).API = origApi;
    pluginsStore.resetForTest();
    document.body.innerHTML = '';
    localStorage.clear();
});

async function settle(): Promise<void> {
    for (let i = 0; i < 8; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

function makeHost(ledger: InstalledItem[] = [LEDGER_AGENT_ROW], uninstallSpy?: (id: string) => void): CatalogHost {
    return {
        listItems: async () => ({ items: [] }),
        listInstalled: async () => ({ items: ledger }),
        listProjects: async () => [{ path: '/tmp/repo-pulse', name: 'repo-pulse' }],
        currentProjectPath: async () => null,
        uninstall: async (installId: string) => {
            uninstallSpy?.(installId);
        },
        setEnabled: async () => {},
        previewInstall: async () => { throw new Error('unexpected'); },
        confirmInstall: async () => { throw new Error('unexpected'); },
        checkUpdates: async () => ({ updates: [] }),
        applyUpdate: async () => { throw new Error('unexpected'); },
        runningSessions: () => [],
        oneShot: async () => {},
    } as unknown as CatalogHost;
}

function makeAdapter(rows: CplugRow[]): ManagerAdapter {
    return {
        list: async () => rows.map((row) => toCplugItem(row, t)),
        setEnabled: async (id: string) => toCplugItem(rows.find((r) => `cplug:${r.id}` === id) ?? rows[0]!, t),
    };
}

function cardNames(root: HTMLElement): string[] {
    return [...root.querySelectorAll('.catalog-card__title')].map((el) => el.textContent?.trim() ?? '');
}

describe('unified Plugins page (M3.2)', () => {
    test('renders origin Tag badges, 6 filter pills, no #plugins-project, and + install from github opens sheet', async () => {
        const host = makeHost();
        const catalog = createCatalogPlugins({ host, t });
        const adapter = makeAdapter([BUILTIN_ROW, APP_PLUGIN_ROW, AGENT_PLUGIN_ROW, LOCAL_DEV_ROW]);
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginsScreen, {
            target,
            props: { embedded: true, scope: 'plugins', adapter, catalog, t, loadActivity: async () => [] },
        });
        await settle();

        expect(target.querySelector('#plugins-project')).toBeNull();
        expect(target.querySelector('.dev-zone')).toBeNull();

        const chips = [...target.querySelectorAll<HTMLButtonElement>('.oc-chip')];
        expect(chips.map((c) => c.textContent?.trim())).toEqual([
            'all',
            'enabled',
            'built-in',
            'app plugin',
            'agent plugin',
            'local dev',
        ]);

        const badgesText = [...target.querySelectorAll('.plug-card__badges')].map((el) => el.textContent?.trim() ?? '');
        expect(badgesText.some((txt) => txt.includes('built-in'))).toBe(true);
        expect(badgesText.some((txt) => txt.includes('app plugin'))).toBe(true);
        expect(badgesText.some((txt) => txt.includes('agent plugin') && txt.includes('unverified'))).toBe(true);
        expect(badgesText.some((txt) => txt.includes('local dev'))).toBe(true);

        chips.find((c) => c.textContent?.trim() === 'agent plugin')!.click();
        await settle();
        expect(cardNames(target)).toEqual(['Repo Pulse']);

        chips.find((c) => c.textContent?.trim() === 'local dev')!.click();
        await settle();
        expect(cardNames(target)).toEqual(['Local Probe']);

        chips.find((c) => c.textContent?.trim() === 'all')!.click();
        await settle();
        expect(cardNames(target)).toHaveLength(4);

        const githubBtn = target.querySelector<HTMLButtonElement>('[data-github-install]')!;
        expect(githubBtn).not.toBeNull();
        githubBtn.click();
        await settle();
        expect(target.querySelector('[data-install-sheet="github"]')).not.toBeNull();
    });

    test('renders PluginHealthPill with StatusChip sibling slot and fires onInspectLogs (or permissions fallback)', async () => {
        const inspectSpy = vi.fn();
        const adapter = makeAdapter([APP_PLUGIN_ROW]);
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginsScreen, {
            target,
            props: {
                embedded: true,
                scope: 'plugins',
                adapter,
                catalog: null,
                t,
                loadActivity: async () => [],
                onInspectLogs: inspectSpy,
            },
        });
        await settle();

        expect(target.querySelector('[data-plugin-badges="acme-clock"]')).not.toBeNull();
        const pill = target.querySelector('.pl-health-pill');
        expect(pill).not.toBeNull();
        expect(pill!.querySelector('[data-pill-status]')?.textContent?.trim()).toBeTruthy();
        const logsBtn = pill!.querySelector<HTMLButtonElement>('[data-pill-logs]')!;
        logsBtn.click();
        await settle();
        expect(inspectSpy).toHaveBeenCalledWith('acme-clock');

        unmount(mounted);
        mounted = null;
        target.innerHTML = '';
        mounted = mount(PluginsScreen, {
            target,
            props: { embedded: true, scope: 'plugins', adapter, catalog: null, t, loadActivity: async () => [] },
        });
        await settle();
        target.querySelector<HTMLButtonElement>('[data-pill-logs]')!.click();
        await settle();
        const drawer = target.querySelector('[data-dev-inspector="acme-clock"]');
        expect(drawer).not.toBeNull();
        expect(drawer!.getAttribute('data-sheet-place')).toBe('float');
        expect(drawer!.querySelector('[data-inspector-title]')?.textContent?.trim()).toBe('Acme Clock');
        drawer!.querySelector<HTMLButtonElement>('[data-inspector-close]')!.click();
        await settle();
        expect(target.querySelector('[data-dev-inspector="acme-clock"]')).toBeNull();
    });

    test('first-enable of sidecar needing consent opens PluginInstallSheet in enable mode', async () => {
        const adapter = makeAdapter([SIDECAR_CONSENT_ROW]);
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginsScreen, {
            target,
            props: {
                embedded: true,
                scope: 'plugins',
                adapter,
                catalog: null,
                loadSheet: async () => ({
                    digest: 'd',
                    body_sha: 'b',
                    grants_sha: 'g',
                    permissions: [{ name: 'notify', risk: 'medium' as const, granted: false }],
                }),
                t,
                loadActivity: async () => [],
            },
        });
        await settle();

        const sw = target.querySelector<HTMLButtonElement>('[role="switch"]')!;
        sw.click();
        await settle();
        expect(target.querySelector('[data-install-sheet="enable"]')).not.toBeNull();
    });

    test('installed agent-plugin exposes uninstall in PluginPane via InstallLedger kind=plugin', async () => {
        const uninstalls: string[] = [];
        const host = makeHost([LEDGER_AGENT_ROW], (id) => uninstalls.push(id));
        const catalog = createCatalogPlugins({ host, t });
        const adapter = makeAdapter([AGENT_PLUGIN_ROW]);
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginsScreen, {
            target,
            props: { embedded: true, scope: 'plugins', adapter, catalog, t, loadActivity: async () => [] },
        });
        await settle();

        target.querySelector<HTMLButtonElement>('.catalog-card__open')!.click();
        await settle();
        expect(target.querySelector('[data-plugin-pane="agent:repo-pulse"]')).not.toBeNull();
        const uninstallBtn = target.querySelector<HTMLButtonElement>('[data-act="uninstall"]');
        expect(uninstallBtn).not.toBeNull();
        uninstallBtn!.click();
        await settle();
        const confirmBtn = Array.from(document.body.querySelectorAll<HTMLButtonElement>('button')).find(
            (b) => b.textContent?.trim() === 'uninstall it',
        );
        confirmBtn?.click();
        await settle();
        expect(uninstalls).toEqual(['inst-agent-99']);
    });

    test('BUG-1: sidecar with disabled (safe mode) and runtime_active=false opens PluginInstallSheet enable mode with runtime toggle', async () => {
        const heldRow = {
            id: 'held-sidecar',
            name: 'Held Sidecar',
            description: 'Runtime disabled',
            version: '1.0.0',
            runtime: 'sidecar',
            tier: 'catalog',
            publisher: 'harbor',
            enabled: false,
            state: 'unavailable',
            detail: 'disabled (safe mode)',
            runtime_active: false,
            consent_required: false,
            permissions: { app: [] },
            grants: { app: [] },
            needs: [],
        } as CplugRow & { runtime_active: boolean };
        const adapter: ManagerAdapter = {
            list: async () => [{ ...toCplugItem(heldRow, t), runtimeActive: false } as ReturnType<typeof toCplugItem>],
            setEnabled: async () => toCplugItem(heldRow, t),
        };
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginsScreen, {
            target,
            props: { embedded: true, scope: 'plugins', adapter, catalog: null, t, loadActivity: async () => [] },
        });
        await settle();

        target.querySelector<HTMLButtonElement>('[role="switch"]')!.click();
        await settle();

        expect(target.querySelector('[data-install-sheet="enable"]')).not.toBeNull();
        const rtCheck = target.querySelector<HTMLInputElement>('[data-runtime-checkbox]');
        expect(rtCheck).not.toBeNull();
        expect(rtCheck!.checked).toBe(true);
    });

    test('BUG-1 & BUG-4: health turn_on_third_party opens enable sheet (not folder popup) and Add to <Project> pre-selects project scope', async () => {
        auth.state = 'signed-in';
        const installCalls: Array<Record<string, unknown>> = [];
        (window as unknown as { API?: unknown }).API = {
            getCatalogItems: async () => ({
                items: [
                    {
                        id: 'octocat/agent-pack',
                        name: 'agent-pack',
                        kind: 'plugin',
                        publisher: 'octocat',
                        latest: '1.0.0',
                        card: { title: 'Agent Pack', brief: 'agent pack', tags: [] },
                        versions: [{ v: '1.0.0', scripts: 0, size: 512, files: 1, digest: 'ap-d' }],
                    },
                ],
            }),
            getCatalogInstalled: async () => ({ items: [] }),
            getProjects: async () => [{ path: '/tmp/repo-pulse', name: 'repo-pulse' }],
            previewCatalogInstall: async () => ({
                item_id: 'octocat/agent-pack',
                version: '1.0.0',
                publisher: 'octocat',
                digest: 'ap-d',
                body_sha: 'ap-b',
                plan_token: 'ap-plan',
                files: [],
            }),
            installCatalogItem: async (body: Record<string, unknown>) => {
                if (body.one_click) {
                    throw { status: 409, body: { code: 'sheet_required' } };
                }
                installCalls.push(body);
                return {
                    install_id: 'inst-ap-1',
                    item_id: 'octocat/agent-pack',
                    name: 'agent-pack',
                    scope: body.scope,
                    project_path: body.project_path,
                };
            },
        };
        globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
            const url = typeof input === 'string' ? input : input.toString();
            const json = (data: unknown, status = 200) =>
                new Response(JSON.stringify(data), { status, headers: { 'Content-Type': 'application/json' } });

            if (url.includes('/cplug-owner/health')) {
                return json({
                    rows: [
                        {
                            id: 'harbor/held-mod',
                            kind: 'plugin',
                            source: 'catalog',
                            word: 'held',
                            reason: 'third_party_off',
                            button: 'turn_on_third_party',
                            version: '1.0.0',
                            data_bytes: 0,
                        },
                    ],
                });
            }
            if (url.includes('/cplug-owner/sideload')) {
                return json({ enabled: false, developer_mode: false, items: [] });
            }
            if (url.includes('/cplugs/held-mod/sheet')) {
                return json({
                    digest: 'hm-d',
                    body_sha: 'hm-b',
                    grants_sha: 'hm-g',
                    permissions: [],
                });
            }
            if (url.includes('/cplugs/held-mod/activity')) {
                return json({ activity: [] });
            }
            if (url.includes('/cplugs/held-mod/inspector')) {
                return json({
                    cplug_id: 'held-mod',
                    state: 'unavailable',
                    paused: false,
                    watchdog: { memory_limit_bytes: 128 * 1024 * 1024, rss_bytes: 0, restart_count: 0 },
                    rpc_trace: [],
                    capability_checks: [],
                    logs_tail: [],
                });
            }
            if (url.includes('/cplugs')) {
                return json({
                    cplugs: [
                        {
                            id: 'held-mod',
                            name: 'Held Mod',
                            description: 'Needs runtime activation',
                            version: '1.0.0',
                            runtime: 'sidecar',
                            tier: 'catalog',
                            publisher: 'harbor',
                            enabled: false,
                            state: 'unavailable',
                            detail: 'disabled (safe mode)',
                            runtime_active: false,
                            consent_required: true,
                            permissions: { app: [] },
                            grants: { app: [] },
                            needs: [],
                        },
                    ],
                });
            }
            return json({});
        }) as unknown as typeof fetch;

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginsScreen, {
            target,
            props: { embedded: true, scope: 'plugins', t, loadActivity: async () => [] },
        });
        await new Promise((r) => setTimeout(r, 25));
        await settle();

        const heldCard = [...target.querySelectorAll<HTMLButtonElement>('.catalog-card__open')].find((b) =>
            b.textContent?.includes('Held Mod'),
        )!;
        expect(heldCard).toBeDefined();
        heldCard.click();
        await new Promise((r) => setTimeout(r, 15));
        await settle();

        const healthBtn = target.querySelector<HTMLButtonElement>('[data-health-button="turn_on_third_party"]')!;
        expect(healthBtn).not.toBeNull();
        healthBtn.click();
        await settle();

        expect(target.querySelector('[data-install-sheet="enable"]')).not.toBeNull();
        expect(target.querySelector<HTMLInputElement>('[data-runtime-checkbox]')!.checked).toBe(true);
        expect(document.body.querySelector('[data-sideload-folder]')).toBeNull();

        target.querySelector<HTMLButtonElement>('[data-install-cancel]')!.click();
        await settle();

        const addCaret = target.querySelector<HTMLButtonElement>('[data-act="add-menu"]')!;
        expect(addCaret).not.toBeNull();
        addCaret.click();
        await settle();
        const toProj = [...document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((el) =>
            el.textContent?.toLowerCase().includes('project'),
        )!;
        toProj.click();
        await settle();
        const repoItem = [...document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((el) =>
            el.textContent?.toLowerCase().includes('repo-pulse'),
        )!;
        repoItem.click();
        await new Promise((r) => setTimeout(r, 15));
        await settle();

        expect(target.querySelector('[data-install-sheet="catalog"]')).not.toBeNull();
        expect(target.querySelector<HTMLInputElement>('input[type="radio"][value="project"]')!.checked).toBe(true);
        expect(target.querySelector<HTMLSelectElement>('[data-install-project]')!.value).toBe('/tmp/repo-pulse');

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await new Promise((r) => setTimeout(r, 15));
        await settle();
        expect(installCalls).toEqual([
            expect.objectContaining({
                item_id: 'octocat/agent-pack',
                scope: 'project',
                project_path: '/tmp/repo-pulse',
            }),
        ]);
    });
});
