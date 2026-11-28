/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, tick, unmount } from 'svelte';

import CatalogScreen from './CatalogScreen.svelte';
import type { CatalogHost } from './catalog';
import type { CatalogItem, InstallRequest } from './types';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

(HTMLElement.prototype as { showPopover?: () => void }).showPopover ??= () => {};
(HTMLElement.prototype as { hidePopover?: () => void }).hidePopover ??= () => {};

const en = createI18n({ locale: 'en' }) as { t(key: string, params?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => en.t(key, params);

const CPLUG_ITEM: CatalogItem = {
    id: 'harbor/clock',
    name: 'clock',
    kind: 'cplug',
    publisher: 'harbor',
    latest: '1.0.0',
    card: { title: 'Clock Plugin', brief: 'sidecar plugin', tags: ['time'] },
    versions: [{ v: '1.0.0', scripts: 0, size: 1024, files: 2, digest: 'abc' }],
};

const SKILL_ITEM: CatalogItem = {
    id: 'alex/deploy',
    name: 'deploy',
    kind: 'skill',
    publisher: 'alex',
    latest: '1.0.0',
    card: { title: 'Deploy Skill', brief: 'ships builds', tags: ['cli'] },
    versions: [{ v: '1.0.0', scripts: 0, size: 1024, files: 2, digest: 'def' }],
};

const AGENT_PLUGIN_ITEM: CatalogItem = {
    id: 'harbor/agent-kit',
    name: 'agent-kit',
    kind: 'plugin',
    publisher: 'harbor',
    latest: '1.0.0',
    card: { title: 'Agent Kit', brief: 'agent plugin', tags: ['agents'] },
    versions: [{ v: '1.0.0', scripts: 0, size: 1024, files: 2, digest: 'ghi' }],
};

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted);
    mounted = null;
    document.body.innerHTML = '';
    window.location.hash = '';
});

async function settle(): Promise<void> {
    for (let i = 0; i < 6; i += 1) {
        await tick();
        await Promise.resolve();
    }
    flushSync();
}

function makeHost(
    opts: {
        runtimeActive?: boolean;
        installSpy?: ReturnType<typeof vi.fn>;
        previewSpy?: ReturnType<typeof vi.fn>;
        applyUpdateSpy?: ReturnType<typeof vi.fn>;
        installed?: readonly Record<string, unknown>[];
        currentProject?: string | null;
    } = {},
): CatalogHost {
    const items = [CPLUG_ITEM, AGENT_PLUGIN_ITEM, SKILL_ITEM];
    return {
        listItems: async () => ({
            index: { as_of: '2026-11-24' },
            items,
            untrusted: [],
        }),
        item: async (id: string) => items.find((i) => i.id === id) ?? ({} as CatalogItem),
        listInstalled: async () => ({ items: [...(opts.installed ?? [])] }),
        previewInstall: opts.previewSpy ?? (async (req: InstallRequest) => ({
            item_id: req.item_id,
            version: '1.0.0',
            publisher: 'harbor',
            digest: 'abc',
            body_sha: 'body-abc',
            plan_token: 'plan-abc',
            size: 1024,
            files: [],
            permissions: { app: [] },
            secrets: [],
            tools: [],
            network_hosts: [],
            lan_hosts: [],
            conflicts: [],
            ...(opts.runtimeActive !== undefined ? { runtime_active: opts.runtimeActive } : {}),
        })),
        install: opts.installSpy ?? (async () => {
            throw { status: 409, body: { code: 'sheet_required' } };
        }),
        uninstall: async () => {},
        patchInstalled: async () => { throw new Error('unused'); },
        applyUpdate: opts.applyUpdateSpy ?? (async () => { throw new Error('unused'); }),
        runningSessions: () => [],
        oneShot: async () => {},
        listProjects: async () => [{ path: '/tmp/demo', name: 'demo' }],
        currentProjectPath: async () => opts.currentProject ?? null,
    } as unknown as CatalogHost;
}

describe('CatalogScreen install sheet routing (M3.2)', () => {
    test('cplug card opens PluginInstallSheet while skill card keeps InstallSheet', async () => {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(CatalogScreen, { target, props: { host: makeHost(), embedded: true, t } });
        await settle();

        const openByTitle = (title: string): HTMLButtonElement =>
            [...target.querySelectorAll<HTMLButtonElement>('.catalog-card__open')].find(
                (btn) => btn.textContent?.trim() === title,
            )!;

        const cplugOpener = openByTitle('Clock Plugin');
        expect(cplugOpener).toBeDefined();
        cplugOpener.click();
        await settle();

        target.querySelector<HTMLButtonElement>('.acts [data-act="install"]')!.click();
        await settle();

        expect(target.querySelector('[data-install-sheet="catalog"]')).not.toBeNull();
        target.querySelector<HTMLButtonElement>('[data-install-cancel]')?.click();
        await settle();
        expect(target.querySelector('[data-install-sheet="catalog"]')).toBeNull();

        const skillOpener = openByTitle('Deploy Skill');
        expect(skillOpener).toBeDefined();
        skillOpener.click();
        await settle();

        target.querySelector<HTMLButtonElement>('.acts [data-act="install"]')!.click();
        await settle();
        expect(target.querySelector('[data-install-sheet]')).toBeNull();
        expect(document.body.querySelector('.sheet__radio')).not.toBeNull();

        document.body.querySelector<HTMLButtonElement>('.modal-overlay [data-modal-close]')?.click();
        await settle();
        expect(document.body.querySelector('.sheet__radio')).toBeNull();
    });

    test('BUG-1: cplug preview with runtime_active=false renders [data-runtime-checkbox] in CatalogScreen', async () => {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(CatalogScreen, {
            target,
            props: { host: makeHost({ runtimeActive: false }), embedded: true, t },
        });
        await settle();

        const cplugOpener = [...target.querySelectorAll<HTMLButtonElement>('.catalog-card__open')].find(
            (btn) => btn.textContent?.trim() === 'Clock Plugin',
        )!;
        cplugOpener.click();
        await settle();

        target.querySelector<HTMLButtonElement>('.acts [data-act="install"]')!.click();
        await settle();

        const rtCheck = target.querySelector<HTMLInputElement>('[data-runtime-checkbox]');
        expect(rtCheck).not.toBeNull();
        expect(rtCheck!.checked).toBe(true);
    });

    test('BUG-4: Add to <Project> on Warez agent-plugin pre-selects project scope and project path', async () => {
        const installSpy = vi.fn(async () => ({ install_id: 'inst-ap', name: 'agent-kit', scope: 'project', project_path: '/tmp/demo' }));
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(CatalogScreen, {
            target,
            props: { host: makeHost({ installSpy }), embedded: true, t },
        });
        await settle();

        const agentOpener = [...target.querySelectorAll<HTMLButtonElement>('.catalog-card__open')].find(
            (btn) => btn.textContent?.trim() === 'Agent Kit',
        )!;
        agentOpener.click();
        await settle();

        target.querySelector<HTMLButtonElement>('.acts [data-act="add-menu"]')!.click();
        await settle();
        const toProj = [...document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((el) =>
            el.textContent?.toLowerCase().includes('project'),
        )!;
        toProj.click();
        await settle();
        const demoItem = [...document.body.querySelectorAll<HTMLElement>('[role="menuitem"]')].find((el) =>
            el.textContent?.toLowerCase().includes('demo'),
        )!;
        demoItem.click();
        await settle();

        expect(target.querySelector('[data-install-sheet="catalog"]')).not.toBeNull();
        expect(target.querySelector<HTMLInputElement>('input[type="radio"][value="project"]')!.checked).toBe(true);
        expect(target.querySelector<HTMLSelectElement>('[data-install-project]')!.value).toBe('/tmp/demo');

        target.querySelector<HTMLButtonElement>('[data-install-enable]')!.click();
        await settle();
        expect(installSpy).toHaveBeenCalledWith(
            expect.objectContaining({ item_id: 'harbor/agent-kit', scope: 'project', project_path: '/tmp/demo' }),
        );
    });

    test('BUG-5: global "/" and "j" shortcuts do not steal focus or move selection while PluginInstallSheet is open', async () => {
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(CatalogScreen, { target, props: { host: makeHost(), embedded: true, t } });
        await settle();

        const cplugOpener = [...target.querySelectorAll<HTMLButtonElement>('.catalog-card__open')].find(
            (btn) => btn.textContent?.trim() === 'Clock Plugin',
        )!;
        cplugOpener.click();
        await settle();
        target.querySelector<HTMLButtonElement>('.acts [data-act="install"]')!.click();
        await settle();

        const modalBtn = target.querySelector<HTMLButtonElement>('[data-install-disabled]')!;
        modalBtn.focus();
        expect(document.activeElement).toBe(modalBtn);

        modalBtn.dispatchEvent(new KeyboardEvent('keydown', { key: '/', bubbles: true, cancelable: true }));
        modalBtn.dispatchEvent(new KeyboardEvent('keydown', { key: 'j', bubbles: true, cancelable: true }));
        await settle();

        expect(document.activeElement).toBe(modalBtn);
        expect(target.querySelector('[data-install-sheet="catalog"]')).not.toBeNull();
    });

    test('#3407: cplug install preview always uses global scope even when currentProjectPath is set, and hides project scope caret', async () => {
        const previewSpy = vi.fn(async (req: InstallRequest) => ({
            item_id: req.item_id,
            version: '1.0.0',
            publisher: 'harbor',
            digest: 'abc',
            body_sha: 'body-abc',
            plan_token: 'plan-abc',
            size: 1024,
            files: [],
            permissions: { app: [] },
            secrets: [],
            tools: [],
            network_hosts: [],
            lan_hosts: [],
            conflicts: [],
        }));
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(CatalogScreen, {
            target,
            props: { host: makeHost({ previewSpy, currentProject: '/tmp/demo' }), embedded: true, t },
        });
        await settle();

        const cplugOpener = [...target.querySelectorAll<HTMLButtonElement>('.catalog-card__open')].find(
            (btn) => btn.textContent?.trim() === 'Clock Plugin',
        )!;
        cplugOpener.click();
        await settle();

        expect(target.querySelector('.acts [data-act="add-menu"]')).toBeNull();

        target.querySelector<HTMLButtonElement>('.acts [data-act="install"]')!.click();
        await settle();

        expect(target.querySelector('[data-install-sheet="catalog"]')).not.toBeNull();
        expect(previewSpy).toHaveBeenCalledWith(
            expect.objectContaining({ item_id: 'harbor/clock', scope: 'global' }),
        );
        expect(previewSpy.mock.calls[0]?.[0]).not.toHaveProperty('project_path');
    });

    test('#3407: clicking Update on a cplug card runs applyUpdate instead of opening Install sheet and keeps state on cancel', async () => {
        const previewSpy = vi.fn(async () => {
            throw new Error('previewInstall must not be called when updating an installed cplug');
        });
        const applyUpdateSpy = vi.fn(async () => ({
            install_id: 'inst-clock',
            item_id: 'harbor/clock',
            kind: 'cplug',
            scope: 'global',
            version: '1.0.0',
            revision: 2,
            update_available: false,
        }));
        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(CatalogScreen, {
            target,
            props: {
                host: makeHost({
                    previewSpy,
                    applyUpdateSpy,
                    currentProject: '/tmp/demo',
                    installed: [
                        {
                            install_id: 'inst-clock',
                            item_id: 'harbor/clock',
                            kind: 'cplug',
                            scope: 'global',
                            version: '0.9.0',
                            revision: 1,
                            update_available: true,
                        },
                    ],
                }),
                embedded: true,
                t,
            },
        });
        await settle();

        const cardUpdateBtn = target.querySelector<HTMLButtonElement>('[data-act="update"]')!;
        expect(cardUpdateBtn).not.toBeNull();
        cardUpdateBtn.click();
        await settle();

        expect(target.querySelector('[data-install-sheet="catalog"]')).toBeNull();
        expect(previewSpy).not.toHaveBeenCalled();

        document.body.querySelector<HTMLButtonElement>('.modal-overlay .modal-btn-cancel, .modal-overlay [data-modal-close]')!.click();
        await settle();
        expect(target.querySelector('[data-act="update"]')).not.toBeNull();
        expect(applyUpdateSpy).not.toHaveBeenCalled();

        target.querySelector<HTMLButtonElement>('[data-act="update"]')!.click();
        await settle();
        document.body.querySelector<HTMLButtonElement>('.modal-overlay .modal-btn-primary')!.click();
        await settle();

        expect(applyUpdateSpy).toHaveBeenCalledWith('inst-clock', { expected_revision: 1 });
        expect(target.querySelector('[data-act="update"]')).toBeNull();
    });
});
