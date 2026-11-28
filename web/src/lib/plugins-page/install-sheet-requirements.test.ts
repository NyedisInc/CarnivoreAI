// @vitest-environment jsdom
import { mount, unmount } from 'svelte';
import { afterEach, describe, expect, test, vi } from 'vitest';
import { ApiError } from '../../opscenter/api/auth.svelte';
import type { CardView } from '../catalog/card';
import type { CatalogHost } from '../catalog/catalog';
import type { InstallPreview, InstalledItem } from '../catalog/types';
import { formatUnmetRequirements, installErrorMessage, type InstallSheetStore } from './install-sheet-model';
import PluginInstallSheet from './PluginInstallSheet.svelte';

const STRINGS: Record<string, string> = {
    'plugins.page.refused.on': 'cannot be turned on: {why}',
    'plugins.page.refused.version': 'needs app version {need}, this build is {have}',
    'plugins.page.refused.core': 'needs {name}, which this build lacks',
    'plugins.page.core.crosstalk': 'crosstalk',
    'plugins.page.install_sheet.title_install': 'install {name}',
    'plugins.page.install_sheet.cta_cancel': 'cancel',
    'plugins.page.install_sheet.cta_install_disabled': 'install disabled',
    'plugins.page.install_sheet.cta_install_enable': 'install & enable',
    'plugins.page.install_sheet.cta_installing': 'installing...',
    'plugins.page.install_sheet.no_permissions': 'no permissions',
    'plugins.page.install_sheet.no_network': 'no network',
};

function t(key: string, vars?: Record<string, string | number>): string {
    let text = STRINGS[key] ?? key;
    if (vars) {
        for (const [k, v] of Object.entries(vars)) {
            text = text.replaceAll(`{${k}}`, String(v));
        }
    }
    return text;
}

const settle = () => new Promise((r) => setTimeout(r, 20));

describe('install-sheet unmet requirements UX (#3405)', () => {
    let mounted: Record<string, unknown> | null = null;

    afterEach(() => {
        if (mounted) {
            unmount(mounted);
            mounted = null;
        }
        document.body.innerHTML = '';
    });

    test('installErrorMessage formats 409 requirements_unmet with exact min_app_version', () => {
        const err = new ApiError('conflict', 409, 'requirements_unmet', {
            detail: {
                code: 'requirements_unmet',
                detail: 'pillpanic cannot be turned on: requires Carnivore 1.16.10 or newer (you have 1.16.9)',
                unmet: { min_app_version: { need: '1.16.10', have: '1.16.9' } },
            },
        });
        expect(installErrorMessage(err, t)).toBe(
            'cannot be turned on: needs app version 1.16.10, this build is 1.16.9',
        );
    });

    test('formatUnmetRequirements formats core + version blockers and returns null when empty', () => {
        expect(formatUnmetRequirements(null, t)).toBeNull();
        expect(formatUnmetRequirements({}, t)).toBeNull();
        expect(
            formatUnmetRequirements(
                { core: ['crosstalk'], min_app_version: { need: '1.16.10', have: '1.16.9' } },
                t,
            ),
        ).toBe('cannot be turned on: needs crosstalk, which this build lacks; needs app version 1.16.10, this build is 1.16.9');
    });

    test('PluginInstallSheet shows unmet_requirements upfront and disables install & enable while keeping install disabled clickable', async () => {
        const preview: InstallPreview = {
            digest: 'd1',
            body_sha: 'b1',
            plan_token: 'p1',
            cplug_facts_sha: 'f1',
            cplug_facts: {
                id: 'pillpanic',
                name: 'Pill Panic',
                description: 'Falling-pill puzzle',
                version: '1.0.0',
                entry: '',
                files: 12,
                bytes: 2048,
                permissions: [],
                tools: [],
                network_hosts: [],
                lan_hosts: [],
                secrets: [],
                unmet_requirements: { min_app_version: { need: '1.16.10', have: '1.16.9' } },
            },
        };
        const host = {
            previewInstall: vi.fn(async () => preview),
            install: vi.fn(async () => ({ install_id: 'i1', name: 'pillpanic' }) as InstalledItem),
            listProjects: vi.fn(async () => []),
        } as unknown as CatalogHost;
        const store: InstallSheetStore = {
            previewGithub: vi.fn(),
            installGithub: vi.fn(),
            updatePlugin: vi.fn(),
        };
        const card = {
            id: 'acme/pillpanic',
            name: 'pillpanic',
            headline: 'Pill Panic',
            version: '1.0.0',
            isCplug: true,
            isPlugin: false,
            untrusted: false,
        } as unknown as CardView;

        const target = document.createElement('div');
        document.body.append(target);
        mounted = mount(PluginInstallSheet, {
            target,
            props: { open: true, mode: 'catalog', card, host, store, t, onClose: vi.fn(), onDone: vi.fn() },
        });
        await settle();

        const banner = target.querySelector('[data-install-unmet]');
        expect(banner?.textContent).toContain('needs app version 1.16.10, this build is 1.16.9');
        expect(target.querySelector<HTMLButtonElement>('[data-install-enable]')!.disabled).toBe(true);
        expect(target.querySelector<HTMLButtonElement>('[data-install-disabled]')!.disabled).toBe(false);
    });
});
