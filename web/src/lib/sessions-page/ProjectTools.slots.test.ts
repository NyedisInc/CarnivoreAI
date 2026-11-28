/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

const authFetchMock = vi.hoisted(() =>
    vi.fn(async (url: string) =>
        url.includes('/ticket') ? { path: '/cplug-view/ticket-1', expires_in: 60 } : { ok: true },
    ),
);

vi.mock('../../opscenter/api/auth.svelte', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../../opscenter/api/auth.svelte')>();
    return {
        ...actual,
        auth: { ...actual.auth, state: 'signed-in' },
        authFetch: authFetchMock,
    };
});
vi.mock('../../opscenter/api/projects.svelte', () => ({
    projects: { data: [] },
}));

import GroupSection from './GroupSection.svelte';
import ProjectToolWindow from './ProjectToolWindow.svelte';
import type { LensGroup } from './lenses';
import { setLocale, t } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { pluginsStore, type SlotContribution, type StoreCplugRow } from '../plugins/store.svelte';
import { toolOf } from './project-tools';

setLocale('en');
installPopoverPolyfill();

const project = { id: 18, name: 'acme', archived_at: null, root: '/a', storage: null, pack_state: null };
const ownGroup = (rows: LensGroup['rows'] = []): LensGroup => ({
    key: 'project:acme',
    label: 'acme',
    bits: [],
    measure: '',
    rows,
    count: 0,
    live: 0,
    project: project as never,
    provider: null,
});

function makePluginRow(overrides: Partial<StoreCplugRow> = {}): StoreCplugRow {
    return {
        id: 'acme.proj',
        name: 'Acme Project',
        enabled: true,
        state: 'active',
        runtime_paused: false,
        granted_ui_slots: ['project.panels'],
        routes: ['refresh_panel'],
        declared_tools: [],
        ...overrides,
    };
}

function seedStore(rows: StoreCplugRow[], slots: Record<string, SlotContribution[]>): void {
    pluginsStore.rows = rows;
    pluginsStore.read = true;
    pluginsStore.slots = slots;
    pluginsStore.slotsRead = true;
}

let handle: ReturnType<typeof mount> | null = null;

beforeEach(() => {
    pluginsStore.resetForTest();
    authFetchMock.mockClear();
});

afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    pluginsStore.resetForTest();
    document.body.innerHTML = '';
    vi.restoreAllMocks();
});

test('toolOf parses project-slot-panel ids safely', () => {
    expect(toolOf('project-slot-panel:acme.proj:overview')).toEqual({
        kind: 'slot-panel',
        pluginId: 'acme.proj',
        entryId: 'overview',
    });
    expect(toolOf('project-slot-panel:broken')).toBeNull();
});

test('GroupSection shows project.panels for local project, hides from paired project, and notifies on click', async () => {
    seedStore(
        [
            makePluginRow(),
            makePluginRow({ id: 'noconsent.proj', granted_ui_slots: [] }),
        ],
        {
            'project.panels': [
                {
                    plugin_id: 'acme.proj',
                    install_key: 'acme.proj',
                    slot: 'project.panels',
                    declared_slot: 'project.panels',
                    item: { id: 'deps', label: 'Dependencies', route: 'refresh_panel', description: 'All deps clean' },
                },
                {
                    plugin_id: 'noconsent.proj',
                    install_key: 'noconsent.proj',
                    slot: 'project.panels',
                    declared_slot: 'project.panels',
                    item: { id: 'leak', label: 'Leak', description: 'Should not show' },
                },
            ],
        },
    );

    const onProjectAction = vi.fn();
    handle = mount(GroupSection, {
        target: document.body,
        props: { group: ownGroup(), onProjectAction, folded: false, t, onFold: vi.fn() },
    });
    flushSync();

    document.querySelector<HTMLElement>('.sp-sec-head')!.dispatchEvent(
        new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }),
    );
    await vi.waitFor(() => expect(document.querySelector('[role="menu"]')).not.toBeNull());

    const slotItem = document.querySelector<HTMLElement>('[data-node="project-slot-panel:acme.proj:deps"]')!;
    expect(slotItem).toBeTruthy();
    expect(document.querySelector('[data-node="project-slot-panel:noconsent.proj:leak"]')).toBeNull();
    expect(slotItem.querySelector('.row-menu-key')).toBeNull();

    slotItem.click();
    expect(onProjectAction).toHaveBeenCalledWith('project-slot-panel:acme.proj:deps', expect.objectContaining({ key: 'project:acme' }));

    void unmount(handle);
    handle = null;
    document.body.innerHTML = '';

    handle = mount(GroupSection, {
        target: document.body,
        props: { group: ownGroup([{ computer: 'studio' } as never]), onProjectAction, folded: false, t, onFold: vi.fn() },
    });
    flushSync();
    document.querySelector<HTMLElement>('.sp-sec-head')!.dispatchEvent(
        new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }),
    );
    expect(document.querySelector('[role="menu"]')).toBeNull();
});

test('ProjectToolWindow renders SlotHost with project_id/project_key and supports ViewFrame when view is set', async () => {
    const acquireSpy = vi.spyOn(pluginsStore, 'acquire').mockImplementation(() => () => {});
    seedStore([makePluginRow()], {
        'project.panels': [
            {
                plugin_id: 'acme.proj',
                install_key: 'acme.proj',
                slot: 'project.panels',
                declared_slot: 'project.panels',
                item: {
                    id: 'deps',
                    label: 'Dependencies',
                    kind: 'action',
                    route: 'refresh_panel',
                },
            },
            {
                plugin_id: 'acme.proj',
                install_key: 'acme.proj',
                slot: 'project.panels',
                declared_slot: 'project.panels',
                item: {
                    id: 'framed',
                    label: 'Framed View',
                    view: 'deps_view',
                },
            },
        ],
    });

    handle = mount(ProjectToolWindow, {
        target: document.body,
        props: {
            tool: { kind: 'slot-panel', pluginId: 'acme.proj', entryId: 'deps' },
            project: { id: 18, name: 'acme' },
            t,
            onClose: vi.fn(),
        },
    });
    flushSync();

    expect(acquireSpy).toHaveBeenCalledWith({ includeSlots: true });
    expect(document.querySelector('[data-project-tool="acme.proj:deps"]')).toBeTruthy();
    expect(document.querySelector('.pw-label')?.textContent).toBe('Dependencies: acme');

    const cta = document.querySelector<HTMLButtonElement>('.pw-body button')!;
    expect(cta).toBeTruthy();
    cta.click();
    await vi.waitFor(() => expect(authFetchMock).toHaveBeenCalledTimes(1));
    const [url, init] = authFetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/cplug-owner/act');
    expect(JSON.parse(String(init.body))).toEqual({
        cplug_id: 'acme.proj',
        route: 'refresh_panel',
        body: { project_id: 18, project_key: '18' },
    });

    void unmount(handle);
    handle = null;
    document.body.innerHTML = '';

    handle = mount(ProjectToolWindow, {
        target: document.body,
        props: {
            tool: { kind: 'slot-panel', pluginId: 'acme.proj', entryId: 'framed' },
            project: { id: 18, name: 'acme' },
            t,
            onClose: vi.fn(),
        },
    });
    flushSync();
    expect(document.querySelector('.pw-label')?.textContent).toBe('Framed View: acme');
    await vi.waitFor(() => expect(document.querySelector('iframe')).toBeTruthy());
});
