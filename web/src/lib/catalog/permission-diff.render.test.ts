/** @vitest-environment jsdom */
import { afterEach, describe, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import { createI18n } from '../../../../client/js/i18n/runtime.js';
import { cardView } from './card';
import type { CatalogHost } from './catalog';
import DetailActions from './DetailActions.svelte';
import { isProvenanceBlocked, parsePermissionDiff, permissionDiffFromError } from './permission-diff';
import type { InstalledItem, UpdateInstalledRequest } from './types';

const i18n = createI18n({ locale: 'en' }) as {
    t(key: string, params?: Record<string, unknown> | null): string;
};
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const INSTALLED: InstalledItem = {
    install_id: 'inst-perm-1',
    item_id: 'acme/plug',
    scope: 'global',
    revision: 3,
    version: '1.0.0',
    update_available: true,
};

function refusal(detail: Record<string, unknown>): Error {
    const error = new Error('HTTP 409') as Error & { status: number; body: unknown; detail: unknown };
    error.status = 409;
    error.detail = detail;
    error.body = { detail };
    return error;
}

const settle = async () => {
    for (let i = 0; i < 40; i += 1) {
        await Promise.resolve();
        flushSync();
    }
};

let handles: Array<Record<string, unknown>> = [];
afterEach(async () => {
    for (let guard = 0; guard < 6; guard += 1) {
        const open = document.querySelector('.modal-overlay');
        if (!open) break;
        open.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
        await settle();
    }
    for (const h of handles) unmount(h);
    handles = [];
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

describe('M5.3 permission-diff ("rug-pull") UI & update flow', () => {
    test('parsePermissionDiff extracts all categories, execution_escalation, and provenance fields', () => {
        const diff = parsePermissionDiff({
            requires_reconsent: true,
            added: {
                read: ['~/.ssh/*'],
                network: ['evil.example.com'],
                secrets: ['GITHUB_TOKEN'],
            },
            removed: {
                events_on: ['session.idle'],
            },
            execution_escalation: {
                tier0_to_run: true,
                run_mode_changed: true,
                run_cmd_changed: true,
                trust_escalated: true,
            },
            provenance: {
                commit_sha_mismatch: false,
                repo_changed: true,
                old_repo: 'acme/plug',
                new_repo: 'other/plug',
                old_tag: 'v1.0.0',
                new_tag: 'v2.0.0',
            },
        });

        expect(diff).not.toBeNull();
        expect(diff?.requiresReconsent).toBe(true);
        expect(diff?.executionEscalation.hasAny).toBe(true);
        expect(diff?.executionEscalation.tier0ToRun).toBe(true);
        expect(diff?.provenance.repoChanged).toBe(true);
        expect(diff?.categories.map((c) => c.category)).toEqual(['read', 'network', 'secrets', 'events_on']);
        expect(isProvenanceBlocked(diff)).toBe(false);

        const errDiff = permissionDiffFromError(
            refusal({
                code: 'commit_sha_mismatch',
                permission_diff: {
                    provenance: {
                        commit_sha_mismatch: true,
                        old_commit_sha: 'aaaa',
                        new_commit_sha: 'bbbb',
                    },
                },
            }),
        );
        expect(isProvenanceBlocked(errDiff)).toBe(true);
    });

    test('widened permissions show PermissionDiffPanel, keep confirm disabled until ticked, and send accept_permission_escalation', async () => {
        const requests: UpdateInstalledRequest[] = [];
        const host = {
            listItems: async () => ({ items: [] }),
            refreshIndex: async () => ({ items: [] }),
            listInstalled: async () => ({ items: [] }),
            previewInstall: async () => ({}),
            install: async () => INSTALLED,
            uninstall: async () => {},
            item: async () => ({}),
            patchInstalled: async () => INSTALLED,
            applyUpdate: async (_id: string, body: UpdateInstalledRequest) => {
                requests.push(body);
                if (requests.length === 1) {
                    throw refusal({
                        code: 'permission_widened',
                        body: '{"id":"acme/plug"}',
                        body_sha: 'sha-v2',
                        digest: 'dg-v2',
                        script_files: [],
                        requires_consent: true,
                        cplug_facts: {
                            id: 'acme/plug',
                            name: 'Plug',
                            description: 'Updated',
                            version: '2.0.0',
                            entry: 'main.py',
                            files: 2,
                            bytes: 400,
                            permissions: [{ name: 'net.fetch', risk: 'high', reason: 'fetch remote config' }],
                            tools: [],
                            network_hosts: [{ host: 'evil.example', methods: ['GET'], paths: ['/'] }],
                            lan_hosts: [],
                            secrets: [],
                        },
                        cplug_facts_sha: 'facts-v2',
                        permission_diff: {
                            requires_reconsent: true,
                            added: { network: ['evil.example'], secrets: ['API_KEY'] },
                            removed: { read: ['./docs'] },
                            execution_escalation: { tier0_to_run: true },
                            provenance: { commit_sha_mismatch: false, repo_changed: false },
                        },
                    });
                }
                return { ...INSTALLED, revision: 4, version: '2.0.0', update_available: false };
            },
            runningSessions: () => [],
            oneShot: async () => ({}),
            listProjects: async () => [],
        } as unknown as CatalogHost;

        const card = cardView(
            { id: 'acme/plug', name: 'plug', latest: '2.0.0', kind: 'cplug', versions: [{ v: '2.0.0' }] } as never,
            false,
        );
        const onLedgerChange = vi.fn();

        handles.push(
            mount(DetailActions, {
                target: document.body,
                props: {
                    card,
                    installed: INSTALLED,
                    rowState: { kind: 'update-available' },
                    host,
                    t,
                    onInstall: vi.fn(),
                    onLedgerChange,
                },
            }),
        );
        flushSync();

        (document.querySelector('[data-act="update"]') as HTMLButtonElement).click();
        await settle();
        (document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement).click();
        await settle();

        const diffEl = document.querySelector('[data-permission-diff]');
        expect(diffEl).not.toBeNull();
        expect(diffEl?.textContent).toContain('evil.example');
        expect(diffEl?.textContent).toContain('API_KEY');
        expect(diffEl?.textContent).toContain('tier 0');

        const confirmBtn = document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement;
        expect(confirmBtn.disabled).toBe(true);

        const cplugTick = document.querySelector('.cplugfacts input') as HTMLInputElement;
        cplugTick.click();
        await settle();
        expect(confirmBtn.disabled).toBe(true);

        const permTick = document.querySelector('[data-perm-diff-ack]') as HTMLInputElement;
        expect(permTick.checked).toBe(false);
        permTick.click();
        await settle();
        expect(confirmBtn.disabled).toBe(false);

        confirmBtn.click();
        await settle();

        expect(requests).toHaveLength(2);
        expect(requests[1]?.consent).toMatchObject({
            body_sha: 'sha-v2',
            digest: 'dg-v2',
            scripts: true,
            accept_permission_escalation: true,
        });
        expect(onLedgerChange).toHaveBeenCalledWith('acme/plug', expect.objectContaining({ version: '2.0.0' }));
    });

    test('commit_sha_mismatch blocks confirmation and surfaces commit_sha_mismatch refusal', async () => {
        const host = {
            listItems: async () => ({ items: [] }),
            refreshIndex: async () => ({ items: [] }),
            listInstalled: async () => ({ items: [] }),
            previewInstall: async () => ({}),
            install: async () => INSTALLED,
            uninstall: async () => {},
            item: async () => ({}),
            patchInstalled: async () => INSTALLED,
            applyUpdate: async () => {
                throw refusal({
                    code: 'commit_sha_mismatch',
                    permission_diff: {
                        requires_reconsent: true,
                        provenance: {
                            commit_sha_mismatch: true,
                            old_commit_sha: '1111aaaa',
                            new_commit_sha: '9999ffff',
                        },
                    },
                });
            },
            runningSessions: () => [],
            oneShot: async () => ({}),
            listProjects: async () => [],
        } as unknown as CatalogHost;

        const card = cardView(
            { id: 'acme/plug', name: 'plug', latest: '2.0.0', kind: 'cplug', versions: [{ v: '2.0.0' }] } as never,
            false,
        );

        handles.push(
            mount(DetailActions, {
                target: document.body,
                props: {
                    card,
                    installed: INSTALLED,
                    rowState: { kind: 'update-available' },
                    host,
                    t,
                    onInstall: vi.fn(),
                    onLedgerChange: vi.fn(),
                },
            }),
        );
        flushSync();

        (document.querySelector('[data-act="update"]') as HTMLButtonElement).click();
        await settle();
        (document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement).click();
        await settle();

        expect(document.querySelector('[data-perm-diff-blocked]')).not.toBeNull();
        expect(document.querySelector('[data-perm-diff-ack]')).toBeNull();
        const confirmBtn = document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement;
        expect(confirmBtn.disabled).toBe(true);

        (document.querySelector('.modal-footer .modal-btn:not(.modal-btn-primary)') as HTMLButtonElement).click();
        await settle();

        expect(document.querySelector('.acts__refusal')?.textContent).toContain('commit sha');
    });

    test('Tier-0 flagged cplug update on 409 cplug_flagged_ack_required renders FlaggedWarningBox without documentMissing and sends both ack flags', async () => {
        const requests: UpdateInstalledRequest[] = [];
        const host = {
            listItems: async () => ({ items: [] }),
            refreshIndex: async () => ({ items: [] }),
            listInstalled: async () => ({ items: [] }),
            previewInstall: async () => ({}),
            install: async () => INSTALLED,
            uninstall: async () => {},
            item: async () => ({}),
            patchInstalled: async () => INSTALLED,
            applyUpdate: async (_id: string, body: UpdateInstalledRequest) => {
                requests.push(body);
                if (requests.length === 1) {
                    throw refusal({
                        code: 'cplug_flagged_ack_required',
                        detail: 'this plugin carries security warnings and requires explicit warning acknowledgment',
                        flagged: true,
                        requires_warning_ack: true,
                        warning_reasons: ['shell hook invoked on session start'],
                        review: {
                            verdict: 'flagged',
                            summary: 'Runs a shell hook on session start.',
                        },
                    });
                }
                return { ...INSTALLED, revision: 4, version: '2.0.0', update_available: false };
            },
            runningSessions: () => [],
            oneShot: async () => ({}),
            listProjects: async () => [],
        } as unknown as CatalogHost;

        const card = cardView(
            { id: 'acme/plug', name: 'plug', latest: '2.0.0', kind: 'cplug', versions: [{ v: '2.0.0' }] } as never,
            false,
        );
        const onLedgerChange = vi.fn();

        handles.push(
            mount(DetailActions, {
                target: document.body,
                props: {
                    card,
                    installed: INSTALLED,
                    rowState: { kind: 'update-available' },
                    host,
                    t,
                    onInstall: vi.fn(),
                    onLedgerChange,
                },
            }),
        );
        flushSync();

        (document.querySelector('[data-act="update"]') as HTMLButtonElement).click();
        await settle();
        (document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement).click();
        await settle();

        expect(document.querySelector('.confirm__missing')).toBeNull();
        expect(document.querySelector('.confirm__accept')).toBeNull();

        const warnBox = document.querySelector('[data-flagged-warning-box]');
        expect(warnBox).not.toBeNull();
        expect(warnBox?.textContent).toContain('Runs a shell hook on session start.');
        expect(warnBox?.textContent).toContain('shell hook invoked on session start');

        const confirmBtn = document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement;
        expect(confirmBtn.disabled).toBe(true);

        const flaggedTick = document.querySelector('[data-flagged-ack]') as HTMLInputElement;
        expect(flaggedTick).not.toBeNull();
        expect(flaggedTick.checked).toBe(false);
        flaggedTick.click();
        await settle();
        expect(confirmBtn.disabled).toBe(false);

        confirmBtn.click();
        await settle();

        expect(requests).toHaveLength(2);
        expect(requests[1]?.consent).toEqual({
            body_sha: '',
            cplug_flagged_ack: true,
            acknowledge_flagged: true,
        });
        expect(onLedgerChange).toHaveBeenCalledWith('acme/plug', expect.objectContaining({ version: '2.0.0' }));
    });

    test('multi-round consent_required -> cplug_flagged_ack_required preserves body_sha, digest, and scripts across rounds', async () => {
        const requests: UpdateInstalledRequest[] = [];
        const host = {
            listItems: async () => ({ items: [] }),
            refreshIndex: async () => ({ items: [] }),
            listInstalled: async () => ({ items: [] }),
            previewInstall: async () => ({}),
            install: async () => INSTALLED,
            uninstall: async () => {},
            item: async () => ({}),
            patchInstalled: async () => INSTALLED,
            applyUpdate: async (_id: string, body: UpdateInstalledRequest) => {
                requests.push(body);
                if (requests.length === 1) {
                    throw refusal({
                        code: 'consent_required',
                        body: '{"id":"acme/plug","version":"2.0.0"}',
                        body_sha: 'sha-round1',
                        digest: 'dg-round1',
                        script_files: ['hooks/run.sh'],
                        requires_consent: true,
                        cplug_facts: {
                            id: 'acme/plug',
                            name: 'Plug',
                            description: 'Updated',
                            version: '2.0.0',
                            entry: 'hooks/run.sh',
                            files: 2,
                            bytes: 400,
                            permissions: [],
                            tools: [],
                            network_hosts: [],
                            lan_hosts: [],
                            secrets: [],
                        },
                        cplug_facts_sha: 'facts-round1',
                    });
                }
                if (requests.length === 2) {
                    throw refusal({
                        code: 'cplug_flagged_ack_required',
                        detail: 'this plugin carries security warnings and requires explicit warning acknowledgment',
                        flagged: true,
                        requires_warning_ack: true,
                        warning_reasons: ['writes outside workspace'],
                        review: {
                            verdict: 'flagged',
                            summary: 'Writes outside workspace.',
                        },
                    });
                }
                return { ...INSTALLED, revision: 4, version: '2.0.0', update_available: false };
            },
            runningSessions: () => [],
            oneShot: async () => ({}),
            listProjects: async () => [],
        } as unknown as CatalogHost;

        const card = cardView(
            { id: 'acme/plug', name: 'plug', latest: '2.0.0', kind: 'cplug', versions: [{ v: '2.0.0' }] } as never,
            false,
        );
        const onLedgerChange = vi.fn();

        handles.push(
            mount(DetailActions, {
                target: document.body,
                props: {
                    card,
                    installed: INSTALLED,
                    rowState: { kind: 'update-available' },
                    host,
                    t,
                    onInstall: vi.fn(),
                    onLedgerChange,
                },
            }),
        );
        flushSync();

        (document.querySelector('[data-act="update"]') as HTMLButtonElement).click();
        await settle();
        (document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement).click();
        await settle();

        expect(document.querySelector('.cplugfacts')).toBeNull();
        (document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement).click();
        await settle();

        expect(document.querySelector('.confirm__missing')).toBeNull();
        expect(document.querySelector('.confirm__accept')).toBeNull();
        expect(document.querySelector('[data-flagged-warning-box]')?.textContent).toContain('Writes outside workspace.');

        const confirmBtn = document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement;
        expect(confirmBtn.disabled).toBe(true);
        (document.querySelector('[data-flagged-ack]') as HTMLInputElement).click();
        await settle();
        expect(confirmBtn.disabled).toBe(false);
        confirmBtn.click();
        await settle();

        expect(requests).toHaveLength(3);
        expect(requests[2]?.consent).toEqual({
            body_sha: 'sha-round1',
            digest: 'dg-round1',
            scripts: true,
            cplug_flagged_ack: true,
            acknowledge_flagged: true,
        });
        expect(onLedgerChange).toHaveBeenCalledWith('acme/plug', expect.objectContaining({ version: '2.0.0' }));
    });

    test('#3408: zero-capability plugin update shows What\u2019s New, version transition, screenshots, collapsed diff, and hides empty permission & CplugFacts boxes', async () => {
        const requests: UpdateInstalledRequest[] = [];
        const host = {
            listItems: async () => ({ items: [] }),
            refreshIndex: async () => ({ items: [] }),
            listInstalled: async () => ({ items: [] }),
            previewInstall: async () => ({}),
            install: async () => INSTALLED,
            uninstall: async () => {},
            item: async () => ({}),
            patchInstalled: async () => INSTALLED,
            applyUpdate: async (_id: string, body: UpdateInstalledRequest) => {
                requests.push(body);
                if (requests.length === 1) {
                    throw refusal({
                        code: 'consent_required',
                        body: 'schema = 2\nid = "pillpanic"\nversion = "1.0.3"\n',
                        body_sha: 'sha-103',
                        digest: 'dg-103',
                        script_files: [],
                        requires_consent: true,
                        flagged: true,
                        requires_warning_ack: true,
                        warning_reasons: ['opaque_payload: minified bundle'],
                        review: { verdict: 'flagged', summary: 'Tier 0 falling-pill puzzle game widget.' },
                        diff: {
                            from_version: '1.0.1',
                            to_version: '1.0.3',
                            unchanged: 6,
                            changes: [
                                {
                                    path: 'views/game/style.css',
                                    status: 'changed',
                                    old_size: 815,
                                    new_size: 1929,
                                    diff: '@@ -1 +1 @@\n+#keys { display: flex; }\n',
                                },
                                {
                                    path: 'README.md',
                                    status: 'changed',
                                    old_size: 900,
                                    new_size: 1125,
                                    diff: '--- a/README.md\n+++ b/README.md\n@@ -12 +12 @@\n+- **↑ / Space / X / Z:** Rotate clockwise or counter-clockwise\n',
                                },
                            ],
                        },
                        cplug_facts: {
                            id: 'acme/pillpanic',
                            name: 'Pill Panic',
                            description: 'Game',
                            version: '1.0.3',
                            entry: '',
                            files: 12,
                            bytes: 2161567,
                            permissions: [],
                            tools: [],
                            network_hosts: [],
                            lan_hosts: [],
                            secrets: [],
                        },
                        permission_diff: {
                            requires_reconsent: false,
                            added: {},
                            removed: {},
                            execution_escalation: {
                                tier0_to_run: false,
                                run_mode_changed: false,
                                run_cmd_changed: false,
                                trust_escalated: false,
                            },
                            provenance: { commit_sha_mismatch: false, repo_changed: false },
                        },
                    });
                }
                return { ...INSTALLED, revision: 4, version: '1.0.3', update_available: false };
            },
            runningSessions: () => [],
            oneShot: async () => ({}),
            listProjects: async () => [],
        } as unknown as CatalogHost;

        const shotSha = 'a'.repeat(64);
        const card = cardView(
            {
                id: 'acme/pillpanic',
                name: 'pillpanic',
                latest: '1.0.3',
                kind: 'cplug',
                card: {
                    title: 'Pill Panic',
                    screenshots: [{ sha256: shotSha, w: 1280, h: 800, type: 'image/webp', caption: 'Active gameplay' }],
                },
                versions: [{ v: '1.0.3' }],
            } as never,
            false,
        );

        handles.push(
            mount(DetailActions, {
                target: document.body,
                props: {
                    card,
                    installed: { ...INSTALLED, item_id: 'acme/pillpanic', version: '1.0.1' },
                    rowState: { kind: 'update-available' },
                    host,
                    t,
                    onInstall: vi.fn(),
                    onLedgerChange: vi.fn(),
                },
            }),
        );
        flushSync();

        (document.querySelector('[data-act="update"]') as HTMLButtonElement).click();
        await settle();
        (document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement).click();
        await settle();

        expect(document.querySelector('[data-update-summary]')).not.toBeNull();
        expect(document.querySelector('[data-update-versions]')?.textContent).toContain('v1.0.1');
        expect(document.querySelector('[data-update-versions]')?.textContent).toContain('v1.0.3');
        expect(document.querySelector('[data-update-notes]')?.textContent).toContain('Rotate clockwise or counter-clockwise');
        expect(document.querySelector(`[data-update-shot="${shotSha}"]`)).not.toBeNull();
        expect(document.querySelector('[data-update-status-pills]')?.textContent).toContain('no permissions');

        expect(document.querySelector('[data-permission-diff]')).toBeNull();
        expect(document.querySelector('.cplugfacts')).toBeNull();

        const fold = document.querySelector('[data-update-technical-fold]');
        expect(fold).not.toBeNull();
        expect(fold?.querySelector('[aria-expanded="false"]')).not.toBeNull();

        const confirmBtn = document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement;
        expect(confirmBtn.textContent?.trim()).toBe('update to v1.0.3');
        expect(confirmBtn.disabled).toBe(true);
        (document.querySelector('[data-flagged-ack]') as HTMLInputElement).click();
        await settle();
        expect(confirmBtn.disabled).toBe(false);
        confirmBtn.click();
        await settle();

        expect(requests).toHaveLength(2);
        expect(requests[1]?.consent).toMatchObject({
            body_sha: 'sha-103',
            digest: 'dg-103',
            cplug_flagged_ack: true,
        });
    });

    test('#3408: unchanged-permission plugin update hides CplugFacts box and shows same-permissions pill', async () => {
        const requests: UpdateInstalledRequest[] = [];
        const host = {
            listItems: async () => ({ items: [] }),
            refreshIndex: async () => ({ items: [] }),
            listInstalled: async () => ({ items: [] }),
            previewInstall: async () => ({}),
            install: async () => INSTALLED,
            uninstall: async () => {},
            item: async () => ({}),
            patchInstalled: async () => INSTALLED,
            applyUpdate: async (_id: string, body: UpdateInstalledRequest) => {
                requests.push(body);
                if (requests.length === 1) {
                    throw refusal({
                        code: 'consent_required',
                        body: 'schema = 2\nid = "acme/plug"\nversion = "1.1.0"\n',
                        body_sha: 'sha-110',
                        digest: 'dg-110',
                        script_files: [],
                        requires_consent: true,
                        release_notes: '- Faster startup time',
                        cplug_facts: {
                            id: 'acme/plug',
                            name: 'Plug',
                            description: 'Updated',
                            version: '1.1.0',
                            entry: 'main.py',
                            files: 2,
                            bytes: 400,
                            permissions: [{ name: 'sessions.read', risk: 'low', reason: 'list sessions' }],
                            tools: [],
                            network_hosts: [],
                            lan_hosts: [],
                            secrets: [],
                        },
                        permission_diff: {
                            requires_reconsent: false,
                            added: {},
                            removed: {},
                            execution_escalation: {
                                tier0_to_run: false,
                                run_mode_changed: false,
                                run_cmd_changed: false,
                                trust_escalated: false,
                            },
                            provenance: { commit_sha_mismatch: false, repo_changed: false },
                        },
                    });
                }
                return { ...INSTALLED, revision: 4, version: '1.1.0', update_available: false };
            },
            runningSessions: () => [],
            oneShot: async () => ({}),
            listProjects: async () => [],
        } as unknown as CatalogHost;

        const card = cardView(
            { id: 'acme/plug', name: 'plug', latest: '1.1.0', kind: 'cplug', versions: [{ v: '1.1.0' }] } as never,
            false,
        );

        handles.push(
            mount(DetailActions, {
                target: document.body,
                props: {
                    card,
                    installed: INSTALLED,
                    rowState: { kind: 'update-available' },
                    host,
                    t,
                    onInstall: vi.fn(),
                    onLedgerChange: vi.fn(),
                },
            }),
        );
        flushSync();

        (document.querySelector('[data-act="update"]') as HTMLButtonElement).click();
        await settle();
        (document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement).click();
        await settle();

        expect(document.querySelector('[data-update-notes]')?.textContent).toContain('Faster startup time');
        expect(document.querySelector('[data-update-status-pills]')?.textContent).toContain('same permissions as before');
        expect(document.querySelector('[data-permission-diff]')).toBeNull();
        expect(document.querySelector('.cplugfacts')).toBeNull();

        const confirmBtn = document.querySelector('.modal-footer .modal-btn-primary') as HTMLButtonElement;
        expect(confirmBtn.disabled).toBe(false);
        confirmBtn.click();
        await settle();
        expect(requests).toHaveLength(2);
    });
});
