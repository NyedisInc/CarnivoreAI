/** @vitest-environment jsdom */
import { afterEach, beforeEach, expect, test, vi } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';
import GroupSection from './GroupSection.svelte';
import ProjectToolWindow from './ProjectToolWindow.svelte';
import FakePanel from './ProjectTools.fake-panel.svelte';
import type { LensGroup } from './lenses';
import { t, setLocale } from '../i18n/index.svelte';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { registerProjectPanel, resetProjectPanels } from '../../cplugs/sdk/project-panels';
import { toolOf, withProjectTools } from './project-tools';

setLocale('en');
installPopoverPolyfill();

const project = { id: 18, name: 'acme', archived_at: null, root: '/a', storage: null, pack_state: null };
const own = (rows: LensGroup['rows'] = []): LensGroup => ({ key: 'project:acme', label: 'acme', bits: [], measure: '', rows, count: 0, live: 0, project: project as never, provider: null });
let handle: ReturnType<typeof mount> | null = null;

beforeEach(() => registerProjectPanel({ id: 'crate.project', labelKey: 'cplug.crate.project.group', component: FakePanel as never, enabled: () => true }));
afterEach(() => {
    if (handle) void unmount(handle);
    handle = null;
    resetProjectPanels();
    document.body.innerHTML = '';
});

async function menuIds(group: LensGroup, onProjectAction = vi.fn()): Promise<string[]> {
    handle = mount(GroupSection, { target: document.body, props: { group, onProjectAction, folded: false, t, onFold: vi.fn() } });
    flushSync();
    document.querySelector<HTMLElement>('.sp-sec-head')!.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, clientX: 5, clientY: 5 }));
    if (!group.rows.some((r) => r.computer)) await vi.waitFor(() => expect(document.querySelector('[role="menu"]')).not.toBeNull());
    return [...document.querySelectorAll('[data-node]')].map((n) => n.getAttribute('data-node') ?? '');
}

test('the menu names the tools and the ids map back to them', () => {
    const ids = withProjectTools([{ id: 'copy-path' }, { id: 'archive-project', sep: true }], [{ id: 'crate.project', labelKey: 'k' }]).map((i) => i.id);
    expect(ids).toEqual(['copy-path', 'project-settings', 'project-panel:crate.project', 'archive-project']);
    expect(toolOf('project-settings')).toEqual({ kind: 'settings' });
    expect(toolOf('project-panel:crate.project')).toEqual({ kind: 'panel', panelId: 'crate.project' });
    expect(toolOf('copy-path')).toBeNull();
});

test('a project of this computer gets the tools in its menu and a pick reaches the page', async () => {
    const onProjectAction = vi.fn();
    const ids = await menuIds(own(), onProjectAction);
    expect(ids).toEqual(expect.arrayContaining(['project-settings', 'project-panel:crate.project']));
    document.querySelector<HTMLElement>('[data-node="project-panel:crate.project"]')!.click();
    expect(onProjectAction).toHaveBeenCalledWith('project-panel:crate.project', expect.objectContaining({ key: 'project:acme' }));
});

test('a paired computer project gets no menu, so no tools', async () => {
    const ids = await menuIds(own([{ computer: 'studio' } as never]));
    expect(ids).toEqual([]);
    expect(document.querySelector('[role="menu"]')).toBeNull();
});

test('the window shows the registered panel with the project key', () => {
    handle = mount(ProjectToolWindow, { target: document.body, props: { tool: { kind: 'panel', panelId: 'crate.project' }, project: { id: 18, name: 'acme' }, t, onClose: vi.fn() } });
    flushSync();
    expect(document.querySelector('[data-fake-panel]')?.getAttribute('data-fake-panel')).toBe('18');
    expect(document.querySelector('.pw-label')?.textContent).toBe('crates: acme');
});
