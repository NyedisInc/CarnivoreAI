/** @vitest-environment jsdom */
import { afterEach, describe, expect, test } from 'vitest';
import { flushSync, mount, unmount } from 'svelte';

import AddSplit from './AddSplit.svelte';
import { addProjectsOf } from './add-projects';
import { installPopoverPolyfill } from '../popover-jsdom-polyfill';
import { quickAdd } from './quick-add';
import type { CatalogHost } from './catalog';
import { createI18n } from '../../../../client/js/i18n/runtime.js';

const i18n = createI18n({ locale: 'en' }) as { t(k: string, p?: Record<string, unknown> | null): string };
const t = (key: string, params?: Record<string, unknown> | null) => i18n.t(key, params);

const ROWS = [
    { name: 'Alpha', path: '/work/alpha' },
    { name: 'Carnivore.ai', path: '/work/cloudecode' },
    { name: 'Gamma', path: '/work/gamma' },
];

let mounted: Record<string, unknown> | null = null;
afterEach(() => {
    if (mounted) unmount(mounted as never);
    mounted = null;
    document.body.innerHTML = '';
});
installPopoverPolyfill();

describe('add to project submenu', () => {
    test('lists projects by display name, viewed first, blocks an installed one, and a pick posts that root', async () => {
        const projects = addProjectsOf(ROWS, '/work/cloudecode/web');
        expect(projects.map((p) => p.name)).toEqual(['Carnivore.ai', 'Alpha', 'Gamma']);
        const picked: Array<[string, string | undefined]> = [];
        const target = document.createElement('div');
        document.body.appendChild(target);
        mounted = mount(AddSplit as never, {
            target,
            props: {
                t, projects, installedAt: ['/work/alpha'], haveGlobal: false,
                onAdd: (kind: string, path?: string) => picked.push([kind, path]),
            } as never,
        }) as never;
        (document.querySelector('[data-act="add-menu"]') as HTMLElement).click();
        flushSync();
        (document.querySelector('[data-node="add-project"]') as HTMLElement).click();
        flushSync();
        const rows = [...document.querySelectorAll('[data-node^="add-project:"]')] as HTMLElement[];
        expect(rows.map((r) => r.textContent)).toEqual([
            expect.stringContaining('Carnivore.ai'), expect.stringContaining('Alpha'), expect.stringContaining('Gamma'),
        ]);
        expect(rows[1]!.getAttribute('aria-disabled')).toBe('true');
        expect(rows[1]!.getAttribute('data-tooltip')).toBe('already installed there');
        rows[2]!.click();
        expect(picked).toEqual([['project', '/work/gamma']]);

        const posted: Array<Record<string, unknown>> = [];
        const host = { install: async (body: Record<string, unknown>) => { posted.push(body); return {}; } } as unknown as CatalogHost;
        await quickAdd(host, 'acme/deploy', 'project', '/work/gamma');
        expect(posted[0]).toMatchObject({ scope: 'project', project_path: '/work/gamma', one_click: true });
    });
});
